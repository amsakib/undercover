import itertools
from pathlib import Path

import pytest
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError
from langchain_core.messages import AIMessage
from langchain_core.rate_limiters import InMemoryRateLimiter

from agent import harness
from agent.tests.stubs import StubModel, call, claim, decision, declines, steps, stub

ROOT = Path(__file__).parent.parent.parent


def kinds(claim_id, kind):
    return [s["text"] for s in steps(claim_id) if s["kind"] == kind]


def test_approve_under_limit_is_paid():
    reply = harness.run_claim_agent(
        "CLM-1001",
        stub(
            call("get_claim"),
            decision("approve", 420),
            call("pay_claim", {"amount": 420}, "3"),
            AIMessage(content="Approved, $420.00."),
        ),
    )
    assert reply == "Approved, $420.00."
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert result["payment"]["amount"] == 420


def test_approve_over_limit_waits_for_sign_off():
    harness.run_claim_agent(
        "CLM-1001",
        stub(
            decision("approve", 1250),
            call("pay_claim", {"amount": 1250}, "3"),
            AIMessage(content="Approved, $1,250.00, waiting for sign-off."),
        ),
    )
    result = claim("CLM-1001")
    assert result["status"] == "awaiting_signoff"
    assert result["payment"] is None
    assert any("Refused (409)" in text for text in kinds("CLM-1001", "tool_result"))


def test_decline_is_not_paid():
    harness.run_claim_agent("CLM-1001", declines())
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert result["payment"] is None


def test_every_step_is_recorded():
    harness.run_claim_agent(
        "CLM-1001",
        stub(
            AIMessage(
                content="Reading the claim.",
                tool_calls=[{"name": "get_claim", "args": {}, "id": "1"}],
            ),
            call("get_policy", {"policy_id": "POL-2001"}, "2"),
            decision("refer", 0, "3"),
            AIMessage(content="Referred."),
        ),
    )
    recorded = steps("CLM-1001")
    assert [s["kind"] for s in recorded] == [
        "message",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "message",
    ]
    assert recorded[1]["text"] == "get_claim {}"
    assert recorded[2]["text"].endswith("...")


def test_the_claim_agent_acts_only_on_its_own_claim():
    harness.run_claim_agent(
        "CLM-1001",
        stub(
            call("get_claim"),
            decision("decline", 0),
            AIMessage(content="Declined."),
        ),
    )
    assert '"claim_id": "CLM-1001"' in kinds("CLM-1001", "tool_result")[0]
    assert claim("CLM-1002")["status"] == "waiting"


def test_sections_read_are_recorded():
    harness.run_claim_agent(
        "CLM-1001",
        stub(
            call("search_documents", {"query": "third claim"}),
            call("get_section", {"document": "manual", "section": "9"}, "2"),
            call("get_section", {"document": "wording", "section": "5"}, "3"),
            call("get_section", {"document": "manual", "section": "99"}, "4"),
            decision("decline", 0, "5"),
            AIMessage(content="Declined."),
        ),
    )
    assert kinds("CLM-1001", "read") == [
        "Claims manual 9. Repeat claims",
        "Policy wording 5. Baggage and Personal Effects",
    ]
    assert "Refused (404)" in kinds("CLM-1001", "tool_result")[3]
    assert claim("CLM-1001")["status"] == "decided"


def test_nothing_reads_the_evals():
    for folder in ["agent", "backend"]:
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in {".py", ".md"} and "tests" not in path.parts:
                assert "evals" not in path.read_text(), path


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_REQUESTS_PER_MINUTE", raising=False)
    default = harness.model()
    assert default.model_name == "deepseek/deepseek-v4.1-flash"
    assert default.reasoning_effort == "low"
    assert default.rate_limiter is None
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert harness.model().model_name == "openrouter/free"
    assert harness.model().reasoning_effort is None


def test_rate_limiter_is_shared(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_REQUESTS_PER_MINUTE", "18")
    first, second = harness.model(), harness.model()
    assert first.rate_limiter is second.rate_limiter
    assert isinstance(first.rate_limiter, InMemoryRateLimiter)
    assert first.rate_limiter.requests_per_second == pytest.approx(0.3)


def test_work_claim_reports_the_decision():
    assert (
        harness.work_claim("CLM-1001", declines()) == "CLM-1001 decline $0.00 decided"
    )


def test_work_claim_over_the_limit_waits_for_sign_off():
    line = harness.work_claim(
        "CLM-1001",
        stub(
            decision("approve", 1250),
            call("pay_claim", {"amount": 1250}, "3"),
            AIMessage(content="Approved."),
        ),
    )
    assert line == "CLM-1001 approve $1,250.00 waiting for sign-off"
    assert claim("CLM-1001")["payment"] is None


def failing(message):
    """A model that fails on every call, through all of its retries."""
    return StubModel(replies=(RuntimeError(message) for _ in itertools.count()))


def test_a_failure_puts_the_claim_back():
    line = harness.work_claim("CLM-1001", failing("the model broke"))
    assert line == (
        "CLM-1001 failed (RuntimeError: the model broke), back in the queue (attempt 1)"
    )
    result = claim("CLM-1001")
    assert result["status"] == "waiting"
    assert result["attempts"] == 1
    assert kinds("CLM-1001", "error") == ["RuntimeError: the model broke"]


def test_a_second_failure_leaves_the_claim_for_a_handler():
    harness.work_claim("CLM-1001", failing("once"))
    line = harness.work_claim("CLM-1001", failing("twice"))
    assert line.endswith("left for a handler after 2 attempts")
    assert claim("CLM-1001")["status"] == "needs_handler"


def test_finishing_without_a_decision_is_a_failure():
    line = harness.work_claim("CLM-1001", stub(AIMessage(content="I am not sure.")))
    assert "without recording a decision" in line
    assert claim("CLM-1001")["status"] == "waiting"


def test_an_agent_that_loops_is_stopped(monkeypatch):
    monkeypatch.setattr(harness, "MAX_MODEL_CALLS", 3)
    looping = StubModel(replies=(call("get_claim") for _ in itertools.count()))
    line = harness.work_claim("CLM-1001", looping)
    assert "ModelCallLimitExceededError" in line
    assert claim("CLM-1001")["status"] == "waiting"


def test_a_provider_error_is_retried():
    harness.work_claim(
        "CLM-1001",
        stub(
            ModelAPIError("502 Bad Gateway"),
            decision("decline", 0),
            AIMessage(content="Declined."),
        ),
    )
    assert claim("CLM-1001")["status"] == "decided"
    assert kinds("CLM-1001", "error") == []


def test_a_rate_limit_is_retried():
    harness.work_claim(
        "CLM-1001",
        stub(
            ModelRateLimitError("429 Too Many Requests"),
            decision("decline", 0),
            AIMessage(content="Declined."),
        ),
    )
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert result["attempts"] == 0
    assert kinds("CLM-1001", "error") == []


def test_a_lasting_rate_limit_stops_without_counting_an_attempt():
    limited = StubModel(
        replies=(ModelRateLimitError("429 Too Many Requests") for _ in range(10))
    )
    with pytest.raises(harness.RateLimitStop, match="rate limit"):
        harness.work_claim("CLM-1001", limited)
    result = claim("CLM-1001")
    assert result["status"] == "waiting"
    assert result["attempts"] == 0
    assert "rate limit" in kinds("CLM-1001", "error")[0]


def test_a_claim_that_is_not_waiting_is_not_worked():
    harness.work_claim("CLM-1001", declines())
    line = harness.work_claim("CLM-1001", declines())
    assert line == "CLM-1001 is decided, not waiting, so it was not worked"
    assert len(kinds("CLM-1001", "tool_call")) == 1


def test_a_failure_before_the_claim_starts(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    line = harness.work_claim("CLM-1001")
    assert (
        line == "CLM-1001 failed before it started (KeyError: 'OPENROUTER_API_KEY'), "
        "still waiting"
    )

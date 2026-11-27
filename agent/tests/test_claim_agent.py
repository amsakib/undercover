import itertools

import pytest
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError
from langchain_core.messages import AIMessage

from agent import main
from agent.tests.stubs import StubModel, call, claim, decision, declines, steps, stub


def test_sections_read_are_recorded():
    main.run(
        "CLM-1001",
        "thread-1",
        stub(
            call("search_documents", {"query": "third claim"}),
            call("get_section", {"document": "manual", "section": "9"}, "2"),
            call("get_section", {"document": "wording", "section": "5"}, "3"),
            call("get_section", {"document": "manual", "section": "99"}, "4"),
            decision("CLM-1001", "decline", 0, "5"),
            AIMessage(content="Declined."),
        ),
    )
    reads = [s["text"] for s in steps("CLM-1001") if s["kind"] == "read"]
    assert reads == [
        "Claims manual 9. Repeat claims",
        "Policy wording 5. Baggage and Personal Effects",
    ]
    assert claim("CLM-1001")["status"] == "decided"


def test_lookup_tools():
    assert "Repeat claims" in main.get_contents.invoke({"document": "manual"})
    section = main.get_section.invoke({"document": "manual", "section": "10"})
    assert "Meals without receipts" in section
    found = main.search_documents.invoke({"query": "wild animal"})
    assert '"section":"7"' in found


def test_work_claim_reports_the_decision():
    line = main.work_claim("CLM-1001", declines("CLM-1001"))
    assert line == "CLM-1001 decline $0.00 decided"


def test_work_claim_over_the_limit_waits_for_sign_off():
    line = main.work_claim(
        "CLM-1001",
        stub(
            decision("CLM-1001", "approve", 1250),
            call("pay_claim", {"claim_id": "CLM-1001", "amount": 1250}, "3"),
            AIMessage(content="Approved."),
        ),
    )
    assert line == "CLM-1001 approve $1,250.00 waiting for sign-off"
    assert claim("CLM-1001")["payment"] is None


def failing(message):
    """A model that fails on every call, through all of its retries."""
    return StubModel(replies=(RuntimeError(message) for _ in itertools.count()))


def test_a_failure_puts_the_claim_back():
    line = main.work_claim("CLM-1001", failing("the model broke"))
    assert line == (
        "CLM-1001 failed (RuntimeError: the model broke), back in the queue "
        "(attempt 1 of 2)"
    )
    result = claim("CLM-1001")
    assert result["status"] == "waiting"
    assert result["attempts"] == 1
    errors = [s for s in steps("CLM-1001") if s["kind"] == "error"]
    assert errors[0]["text"] == "RuntimeError: the model broke"


def test_a_second_failure_leaves_the_claim_for_a_handler():
    main.work_claim("CLM-1001", failing("once"))
    line = main.work_claim("CLM-1001", failing("twice"))
    assert line.endswith("left for a handler after 2 attempts")
    assert claim("CLM-1001")["status"] == "needs_handler"


def test_finishing_without_a_decision_is_a_failure():
    line = main.work_claim("CLM-1001", stub(AIMessage(content="I am not sure.")))
    assert "without recording a decision" in line
    assert claim("CLM-1001")["status"] == "waiting"


def test_an_agent_that_loops_is_stopped(monkeypatch):
    monkeypatch.setattr(main, "MAX_MODEL_CALLS", 3)
    looping = StubModel(
        replies=(call("get_claim", {"claim_id": "CLM-1001"}) for _ in itertools.count())
    )
    line = main.work_claim("CLM-1001", looping)
    assert "ModelCallLimitExceededError" in line
    assert claim("CLM-1001")["status"] == "waiting"


def test_a_provider_error_is_retried():
    main.work_claim(
        "CLM-1001",
        stub(
            ModelAPIError("502 Bad Gateway"),
            decision("CLM-1001", "decline", 0),
            AIMessage(content="Declined."),
        ),
    )
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert not [s for s in steps("CLM-1001") if s["kind"] == "error"]


def test_a_rate_limit_is_retried():
    main.work_claim(
        "CLM-1001",
        stub(
            ModelRateLimitError("429 Too Many Requests"),
            decision("CLM-1001", "decline", 0),
            AIMessage(content="Declined."),
        ),
    )
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert result["attempts"] == 0
    assert not [s for s in steps("CLM-1001") if s["kind"] == "error"]


def test_a_lasting_rate_limit_stops_without_counting_an_attempt():
    limited = StubModel(
        replies=(ModelRateLimitError("429 Too Many Requests") for _ in range(10))
    )
    with pytest.raises(main.RateLimitStop, match="rate limit"):
        main.work_claim("CLM-1001", limited)
    result = claim("CLM-1001")
    assert result["status"] == "waiting"
    assert result["attempts"] == 0
    errors = [s for s in steps("CLM-1001") if s["kind"] == "error"]
    assert "rate limit" in errors[0]["text"]


def test_a_claim_that_is_not_waiting_is_not_worked():
    main.work_claim("CLM-1001", declines("CLM-1001"))
    line = main.work_claim("CLM-1001", declines("CLM-1001"))
    assert line == "CLM-1001 is decided, not waiting, so it was not worked"
    assert len([s for s in steps("CLM-1001") if s["kind"] == "tool_call"]) == 1


def test_a_failure_before_the_claim_starts(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    line = main.work_claim("CLM-1001")
    assert (
        line == "CLM-1001 failed before it started (KeyError: 'OPENROUTER_API_KEY'), "
        "still waiting"
    )

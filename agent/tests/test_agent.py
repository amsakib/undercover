from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.rate_limiters import InMemoryRateLimiter

from agent import main
from agent.tests.stubs import call, claim, decision, stub
from backend.main import app

ROOT = Path(__file__).parent.parent.parent


def test_approve_under_limit_is_paid():
    reply = main.run(
        "CLM-1001",
        "thread-1",
        stub(
            call("get_claim", {"claim_id": "CLM-1001"}),
            decision("CLM-1001", "approve", 420),
            call("pay_claim", {"claim_id": "CLM-1001", "amount": 420}, "3"),
            AIMessage(content="Approved, $420.00."),
        ),
    )
    assert reply == "Approved, $420.00."
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert result["payment"]["amount"] == 420


def test_approve_over_limit_waits_for_sign_off():
    main.run(
        "CLM-1001",
        "thread-1",
        stub(
            decision("CLM-1001", "approve", 1250),
            call("pay_claim", {"claim_id": "CLM-1001", "amount": 1250}, "3"),
            AIMessage(content="Approved, $1,250.00, waiting for sign-off."),
        ),
    )
    result = claim("CLM-1001")
    assert result["status"] == "awaiting_signoff"
    assert result["payment"] is None
    steps = TestClient(app).get("/api/claims/CLM-1001/steps").json()
    assert any(
        s["kind"] == "tool_result" and "Refused (409)" in s["text"] for s in steps
    )


def test_decline_is_not_paid():
    main.run(
        "CLM-1001",
        "thread-1",
        stub(decision("CLM-1001", "decline", 0), AIMessage(content="Declined.")),
    )
    result = claim("CLM-1001")
    assert result["status"] == "decided"
    assert result["payment"] is None


def test_every_step_is_recorded():
    main.run(
        "CLM-1001",
        "thread-1",
        stub(
            AIMessage(
                content="Reading the claim.",
                tool_calls=[
                    {"name": "get_claim", "args": {"claim_id": "CLM-1001"}, "id": "1"}
                ],
            ),
            call("get_claim", {"claim_id": "CLM-1002"}, "2"),
            decision("CLM-1001", "refer", 0),
            AIMessage(content="Referred."),
        ),
    )
    steps = TestClient(app).get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == [
        "message",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "message",
    ]
    assert steps[1]["text"] == 'get_claim {"claim_id": "CLM-1001"}'
    assert steps[4]["text"].endswith("...")


def test_read_tools():
    assert "POL-2001" in main.get_policy.invoke({"policy_id": "POL-2001"})
    assert "CLM-0412" in main.get_claim_history.invoke({"customer_id": "CUS-3001"})
    assert "per_item_limit" in main.get_plan.invoke({"plan": "first"})


def test_nothing_reads_the_evals():
    for folder in ["agent", "backend"]:
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in {".py", ".md"} and "tests" not in path.parts:
                assert "evals" not in path.read_text(), path


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_REQUESTS_PER_MINUTE", raising=False)
    default = main.model()
    assert default.model_name == "deepseek/deepseek-v4.1-flash"
    assert default.reasoning_effort == "low"
    assert default.rate_limiter is None
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
    assert main.model().reasoning_effort is None


def test_rate_limiter_is_shared(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_REQUESTS_PER_MINUTE", "18")
    first, second = main.model(), main.model()
    assert first.rate_limiter is second.rate_limiter
    assert isinstance(first.rate_limiter, InMemoryRateLimiter)
    assert first.rate_limiter.requests_per_second == pytest.approx(0.3)


def test_claim_stays_waiting_without_a_model(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(KeyError):
        main.run("CLM-1001", "thread-1")
    assert claim("CLM-1001")["status"] == "waiting"

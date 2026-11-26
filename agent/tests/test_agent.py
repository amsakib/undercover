from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import main
from backend.main import app

ROOT = Path(__file__).parent.parent.parent


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))


def call(name, args, n="1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": n}])


def decision(claim_id, kind, payout):
    return call(
        "record_decision",
        {
            "claim_id": claim_id,
            "decision": kind,
            "payout": payout,
            "reasons": "Covered by the wording.",
            "policy_section": "Section 3. Trip Delay",
        },
        "2",
    )


def stub(*replies):
    return StubModel(messages=iter(replies))


def claim(claim_id):
    return TestClient(app).get(f"/api/claims/{claim_id}").json()


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
            call("get_policy_wording", {}, "2"),
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


def test_cli_works_waiting_claims_in_order(monkeypatch, capsys):
    worked = []
    monkeypatch.setattr(
        main, "run", lambda claim_id, thread_id: worked.append(claim_id)
    )
    TestClient(app).post("/api/claims/CLM-1002/start")
    cli.main([])
    assert worked[:2] == ["CLM-1001", "CLM-1003"]
    assert len(worked) == 24
    assert "CLM-1001  no decision  waiting" in capsys.readouterr().out


def test_cli_works_one_claim(monkeypatch, capsys):
    run = main.run

    def decide(claim_id, thread_id):
        run(claim_id, thread_id, stub(decision(claim_id, "decline", 0), AIMessage(".")))

    monkeypatch.setattr(main, "run", decide)
    cli.main(["CLM-1004"])
    assert capsys.readouterr().out.strip() == "CLM-1004  decline  $0.00  decided"
    assert claim("CLM-1001")["status"] == "waiting"


def test_nothing_reads_the_evals():
    for folder in ["agent", "backend"]:
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in {".py", ".md"} and "tests" not in path.parts:
                assert "evals" not in path.read_text(), path


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "openai/gpt-6-luna"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"


def test_claim_stays_waiting_without_a_model(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(KeyError):
        main.run("CLM-1001", "thread-1")
    assert claim("CLM-1001")["status"] == "waiting"

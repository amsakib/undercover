import json
from pathlib import Path

from backend.db import connect

DATA = Path(__file__).parent.parent.parent / "data"


def test_seed_loads_the_queue_in_order(client):
    claims = client.get("/api/claims").json()
    queue = json.loads((DATA / "claims.json").read_text())
    assert [c["claim_id"] for c in claims] == [c["claim_id"] for c in queue]
    assert len(claims) == 25
    assert {c["status"] for c in claims} == {"waiting"}
    assert claims[0]["claim_id"] == "CLM-1001"


def test_seed_leaves_out_evals_and_security():
    conn = connect()
    held_out = json.loads((DATA / "evals" / "held_out_claims.json").read_text())
    held_out_ids = {c["claim_id"] for c in held_out}
    claim_ids = {r[0] for r in conn.execute("SELECT claim_id FROM claims")}
    assert "CLM-1901" not in claim_ids
    assert not claim_ids & held_out_ids
    dump = "\n".join(conn.iterdump())
    assert "CLM-1901" not in dump
    assert "failure_class" not in dump


def test_seed_runs_once():
    connect().close()
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 25


def test_get_claim(client):
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["story"].startswith("My flight home from Rome")
    assert len(claim["items"]) == 3
    assert len(claim["documents"]) == 4
    assert claim["status"] == "waiting"
    assert claim["decision"] is None
    assert claim["payment"] is None


def test_get_policy(client):
    policy = client.get("/api/policies/POL-2001").json()
    assert policy["plan"] == "premium"


def test_get_claim_history_has_no_personal_details(client):
    history = client.get("/api/customers/CUS-3001/claim-history").json()
    assert history[0]["claim_id"] == "CLM-0412"
    text = json.dumps(history)
    for field in ["email", "phone", "address", "date_of_birth"]:
        assert field not in text


def test_get_plan(client):
    plan = client.get("/api/plans/economy").json()
    assert plan["deductible"] == 100.0
    assert plan["deductible_applies_to"] == ["baggage", "emergency_medical"]
    assert {a["add_on"] for a in plan["add_ons"]} == {
        "adventure_sports",
        "pre_existing_waiver",
        "electronics_plus",
    }


def test_get_policy_wording(client):
    text = client.get("/api/policy-wording").json()["text"]
    assert text.startswith("# UnderCover Travel Insurance: Policy Wording")


def test_get_instructions(client):
    assert "UnderCover Agent" in client.get("/api/instructions").json()["text"]


def test_list_handlers(client):
    handlers = client.get("/api/handlers").json()
    assert [h["handler_id"] for h in handlers] == ["HND-01", "HND-02", "HND-03"]


def test_unknown_ids_are_404(client):
    for path in [
        "/api/claims/CLM-0000",
        "/api/policies/POL-0000",
        "/api/customers/CUS-0000/claim-history",
        "/api/plans/gold",
    ]:
        assert client.get(path).status_code == 404, path

import pytest


def decide(client, claim_id, decision="approve", payout=200.0):
    client.post(f"/api/claims/{claim_id}/start")
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "reasons": "The delay is covered.",
            "policy_section": "Section 3. Trip Delay",
        },
    )


def test_start_claim(client):
    response = client.post("/api/claims/CLM-1001/start")
    assert response.json()["status"] == "in_progress"
    assert client.post("/api/claims/CLM-1001/start").status_code == 409


def test_start_unknown_claim(client):
    assert client.post("/api/claims/CLM-0000/start").status_code == 404


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_decline_and_refer_are_decided(client, decision):
    claim = decide(client, "CLM-1001", decision, 0).json()
    assert claim["status"] == "decided"
    assert claim["decision"]["decision"] == decision
    assert claim["decision"]["policy_section"] == "Section 3. Trip Delay"
    paid = client.post("/api/claims/CLM-1001/payments", json={"amount": 1})
    assert paid.status_code == 409


def test_decline_with_payout_is_409(client):
    assert decide(client, "CLM-1001", "decline", 50).status_code == 409


def test_decision_needs_claim_in_progress(client):
    response = client.post(
        "/api/claims/CLM-1001/decision",
        json={
            "decision": "decline",
            "payout": 0,
            "reasons": "x",
            "policy_section": "x",
        },
    )
    assert response.status_code == 409


def test_approve_at_limit_is_paid(client):
    claim = decide(client, "CLM-1001", payout=1000.0).json()
    assert claim["status"] == "decided"
    assert claim["payment"] is None
    paid = client.post("/api/claims/CLM-1001/payments", json={"amount": 1000.0})
    assert paid.json()["payment"]["amount"] == 1000.0
    assert paid.json()["payment"]["paid_by"] == "UnderCover Agent"


def test_payment_must_match_payout(client):
    decide(client, "CLM-1001", payout=200.0)
    paid = client.post("/api/claims/CLM-1001/payments", json={"amount": 250.0})
    assert paid.status_code == 409


def test_second_payment_is_409(client):
    decide(client, "CLM-1001", payout=200.0)
    client.post("/api/claims/CLM-1001/payments", json={"amount": 200.0})
    again = client.post("/api/claims/CLM-1001/payments", json={"amount": 200.0})
    assert again.status_code == 409


def test_payment_over_limit_waits_for_sign_off(client):
    claim = decide(client, "CLM-1001", payout=1250.0).json()
    assert claim["status"] == "awaiting_signoff"
    paid = client.post("/api/claims/CLM-1001/payments", json={"amount": 1250.0})
    assert paid.status_code == 409
    assert "sign-off" in paid.json()["detail"]
    assert client.get("/api/claims/CLM-1001").json()["payment"] is None


def test_sign_off_pays(client):
    decide(client, "CLM-1001", payout=1250.0)
    claim = client.post(
        "/api/claims/CLM-1001/sign-off", json={"handler_id": "HND-02"}
    ).json()
    assert claim["status"] == "decided"
    assert claim["decision"]["signed_off_by"] == "HND-02"
    assert claim["payment"] == {
        "amount": 1250.0,
        "paid_by": "HND-02",
        "paid_at": claim["payment"]["paid_at"],
    }


def test_sign_off_needs_awaiting_signoff(client):
    decide(client, "CLM-1001", payout=200.0)
    response = client.post(
        "/api/claims/CLM-1001/sign-off", json={"handler_id": "HND-01"}
    )
    assert response.status_code == 409


def test_sign_off_unknown_handler(client):
    decide(client, "CLM-1001", payout=1250.0)
    response = client.post(
        "/api/claims/CLM-1001/sign-off", json={"handler_id": "HND-99"}
    )
    assert response.status_code == 404


def test_steps_in_order(client):
    for i in range(3):
        client.post(
            "/api/claims/CLM-1001/steps", json={"kind": "message", "text": str(i)}
        )
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["text"] for s in steps] == ["0", "1", "2"]
    assert client.get("/api/claims/CLM-0000/steps").status_code == 404


def test_every_operation_is_named_and_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    operations = [op for path in paths.values() for op in path.values()]
    assert len(operations) == 23
    for op in operations:
        assert op["operationId"]
        assert op["summary"] or op["description"]

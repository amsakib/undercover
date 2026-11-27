import pytest

from backend.tests.test_write import decide


def release(client, claim_id, counts=True):
    return client.post(
        f"/api/claims/{claim_id}/release",
        json={"reason": "The model timed out.", "counts_as_attempt": counts},
    )


def test_contents(client):
    manual = client.get("/api/documents/manual").json()
    assert manual["title"] == "UnderCover Claims Handling Manual"
    assert manual["intro"].startswith("Version 2026.2")
    assert len(manual["sections"]) == 14
    assert manual["sections"][8] == {"section": "9", "title": "Repeat claims"}
    wording = client.get("/api/documents/wording").json()
    assert len(wording["sections"]) == 12


def test_section(client):
    section = client.get("/api/documents/manual/sections/9").json()
    assert section["title"] == "Repeat claims"
    assert "third claim within any 12 month period" in section["text"]
    assert not section["text"].startswith("##")


@pytest.mark.parametrize(
    "path",
    [
        "/api/documents/handbook",
        "/api/documents/manual/sections/99",
        "/api/documents/handbook/sections/1",
    ],
)
def test_unknown_document_or_section_is_404(client, path):
    assert client.get(path).status_code == 404


def test_search(client):
    found = client.get("/api/documents/search", params={"query": "wild animal"}).json()
    assert {"document": "manual", "section": "7"} in [
        {"document": f["document"], "section": f["section"]} for f in found
    ]
    assert "wild animal" in found[0]["excerpt"].lower()
    meals = client.get(
        "/api/documents/search", params={"query": "receipts meals"}
    ).json()
    assert ("manual", "10") in [(f["document"], f["section"]) for f in meals]
    none = client.get("/api/documents/search", params={"query": "zeppelin"}).json()
    assert none == []


def test_release_puts_claim_back(client):
    client.post("/api/claims/CLM-1001/start")
    claim = release(client, "CLM-1001").json()
    assert claim["status"] == "waiting"
    assert claim["attempts"] == 1
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert steps[-1]["kind"] == "error"
    assert steps[-1]["text"] == "The model timed out."


def test_second_failure_leaves_claim_for_handler(client):
    client.post("/api/claims/CLM-1001/start")
    release(client, "CLM-1001")
    client.post("/api/claims/CLM-1001/start")
    claim = release(client, "CLM-1001").json()
    assert claim["status"] == "needs_handler"
    assert claim["attempts"] == 2
    assert client.post("/api/claims/CLM-1001/start").status_code == 409


def test_release_that_does_not_count(client):
    client.post("/api/claims/CLM-1001/start")
    claim = release(client, "CLM-1001", counts=False).json()
    assert claim["status"] == "waiting"
    assert claim["attempts"] == 0


def test_release_needs_claim_in_progress(client):
    assert release(client, "CLM-1001").status_code == 409
    decide(client, "CLM-1002", payout=1250.0)
    assert release(client, "CLM-1002").status_code == 409
    decide(client, "CLM-1003", "decline", 0)
    assert release(client, "CLM-1003").status_code == 409
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["status"] == "decided"
    assert claim["attempts"] == 0


def test_decided_claim_is_never_decided_or_paid_twice(client):
    decide(client, "CLM-1001", payout=200.0)
    client.post("/api/claims/CLM-1001/payments", json={"amount": 200.0})
    assert client.post("/api/claims/CLM-1001/start").status_code == 409
    again = decide(client, "CLM-1001", "decline", 0)
    assert again.status_code == 409
    paid = client.post("/api/claims/CLM-1001/payments", json={"amount": 200.0})
    assert paid.status_code == 409


def test_released_claim_is_decided_once(client):
    client.post("/api/claims/CLM-1001/start")
    release(client, "CLM-1001")
    assert decide(client, "CLM-1001", "decline", 0).json()["status"] == "decided"
    assert decide(client, "CLM-1001", "decline", 0).status_code == 409


def test_runs_and_todos(client):
    assert client.get("/api/runs/latest").status_code == 404
    run = client.post("/api/runs", json={"claim_limit": 5}).json()
    assert run["status"] == "running"
    assert run["todos"] == []
    todos = [
        {"text": "Work CLM-1001", "status": "done", "claim_id": "CLM-1001"},
        {"text": "Work CLM-1002", "status": "in_progress", "claim_id": "CLM-1002"},
        {"text": "Work CLM-1003", "status": "handler", "claim_id": "CLM-1003"},
        {"text": "Check the queue", "status": "todo", "claim_id": None},
    ]
    client.put(f"/api/runs/{run['run_id']}/todos", json=todos)
    latest = client.get("/api/runs/latest").json()
    assert latest["todos"] == todos
    assert latest["claim_limit"] == 5
    bad = [{"text": "x", "status": "maybe", "claim_id": None}]
    assert client.put(f"/api/runs/{run['run_id']}/todos", json=bad).status_code == 422
    finished = client.post(
        f"/api/runs/{run['run_id']}/finish", json={"summary": "Three claims."}
    ).json()
    assert finished["status"] == "finished"
    assert finished["summary"] == "Three claims."
    assert finished["finished_at"]
    assert client.put("/api/runs/99/todos", json=[]).status_code == 404


def test_run_needs_a_positive_limit(client):
    assert client.post("/api/runs", json={"claim_limit": 0}).status_code == 422

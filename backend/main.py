"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.db import connect, setting

INSTRUCTIONS = Path(__file__).parent / "instructions"
MAX_ATTEMPTS = 2
EXCERPT = 200

app = FastAPI(title="UnderCover")


def get_db() -> Iterator[sqlite3.Connection]:
    """Open a database connection for one request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


DB = Annotated[sqlite3.Connection, Depends(get_db)]


def fetch(conn: sqlite3.Connection, table: str, key: str, value: str) -> Any:
    """Return one record's data by its key, or raise a 404."""
    row = conn.execute(
        f"SELECT data FROM {table} WHERE {key} = ?",  # noqa: S608
        (value,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No {key} {value}")
    return json.loads(row["data"])


def claim_row(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return a claim's status and attempts, or raise a 404."""
    row = conn.execute(
        "SELECT status, attempts FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No claim_id {claim_id}")
    return row


def claim_status(conn: sqlite3.Connection, claim_id: str) -> str:
    """Return a claim's status, or raise a 404."""
    return claim_row(conn, claim_id)["status"]


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(conn: DB) -> list[dict[str, Any]]:
    """List the claims queue in order, with each claim's status."""
    rows = conn.execute("SELECT status, attempts, data FROM claims ORDER BY position")
    claims = []
    for row in rows:
        data = json.loads(row["data"])
        claims.append(
            {
                "claim_id": data["claim_id"],
                "claim_type": data["claim_type"],
                "summary": data["summary"],
                "submitted_on": data["submitted_on"],
                "amount_claimed": data["amount_claimed"],
                "status": row["status"],
                "attempts": row["attempts"],
            }
        )
    return claims


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: DB) -> dict[str, Any]:
    """Get one claim in full, with its decision and payment if any."""
    claim = fetch(conn, "claims", "claim_id", claim_id)
    decision = conn.execute(
        "SELECT decision, payout, reasons, policy_section, decided_at, "
        "signed_off_by, signed_off_at FROM decisions WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()
    payment = conn.execute(
        "SELECT amount, paid_by, paid_at FROM payments WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()
    row = claim_row(conn, claim_id)
    return {
        **claim,
        "status": row["status"],
        "attempts": row["attempts"],
        "decision": dict(decision) if decision else None,
        "payment": dict(payment) if payment else None,
    }


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, conn: DB) -> dict[str, Any]:
    """Get one policy."""
    return fetch(conn, "policies", "policy_id", policy_id)


@app.get("/api/customers/{customer_id}/claim-history", operation_id="get_claim_history")
def get_claim_history(customer_id: str, conn: DB) -> list[dict[str, Any]]:
    """Get a customer's earlier claims, without their personal details."""
    return fetch(conn, "customers", "customer_id", customer_id)["previous_claims"]


@app.get("/api/plans/{plan}", operation_id="get_plan")
def get_plan(plan: str, conn: DB) -> dict[str, Any]:
    """Get one plan's limits, with the add-ons and where the deductible applies."""
    return {
        **fetch(conn, "plans", "plan", plan),
        "deductible_applies_to": setting(conn, "deductible_applies_to"),
        "add_ons": setting(conn, "add_ons"),
    }


@app.get("/api/documents/search", operation_id="search_documents")
def search_documents(query: str, conn: DB) -> list[dict[str, str]]:
    """Find the sections of the wording and the manual holding every query word."""
    words = query.lower().split()
    rows = conn.execute(
        "SELECT document, section, title, text FROM sections "
        "ORDER BY document DESC, position"
    )
    found = []
    for row in rows:
        text = row["text"].lower()
        if words and all(w in text or w in row["title"].lower() for w in words):
            start = max(text.find(words[0]) - EXCERPT // 2, 0)
            found.append(
                {
                    "document": row["document"],
                    "section": row["section"],
                    "title": row["title"],
                    "excerpt": row["text"][start : start + EXCERPT],
                }
            )
    return found


@app.get("/api/documents/{document}", operation_id="get_contents")
def get_contents(document: str, conn: DB) -> dict[str, Any]:
    """Get a document's title, introduction and list of sections."""
    row = conn.execute(
        "SELECT title, intro FROM documents WHERE document = ?", (document,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No document {document}")
    sections = conn.execute(
        "SELECT section, title FROM sections WHERE document = ? ORDER BY position",
        (document,),
    )
    return {**dict(row), "sections": [dict(s) for s in sections]}


@app.get("/api/documents/{document}/sections/{section}", operation_id="get_section")
def get_section(document: str, section: str, conn: DB) -> dict[str, str]:
    """Get one section of a document."""
    row = conn.execute(
        "SELECT document, section, title, text FROM sections "
        "WHERE document = ? AND section = ?",
        (document, section),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No section {section} in {document}")
    return dict(row)


@app.get("/api/instructions/{name}", operation_id="get_instructions")
def get_instructions(name: str) -> dict[str, str]:
    """Get the agent's instructions for running the queue or working a claim."""
    if name not in {"queue", "claim"}:
        raise HTTPException(404, f"No instructions {name}")
    return {"text": (INSTRUCTIONS / f"{name}.md").read_text(encoding="utf-8")}


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(conn: DB) -> list[dict[str, Any]]:
    """List the claims handlers."""
    rows = conn.execute("SELECT data FROM handlers ORDER BY handler_id")
    return [json.loads(row["data"]) for row in rows]


class Step(BaseModel):
    kind: Literal["tool_call", "tool_result", "message", "read", "error"]
    text: str


class Release(BaseModel):
    reason: str
    counts_as_attempt: bool


class RunStart(BaseModel):
    claim_limit: int = Field(ge=1)


class Todo(BaseModel):
    text: str
    status: Literal["todo", "in_progress", "done", "handler"]
    claim_id: str | None


class RunFinish(BaseModel):
    summary: str


class Decision(BaseModel):
    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(ge=0)
    reasons: str
    policy_section: str


class Payment(BaseModel):
    amount: float = Field(gt=0)


class SignOff(BaseModel):
    handler_id: str


def now() -> str:
    """Return the current time in UTC as ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def set_status(conn: sqlite3.Connection, claim_id: str, status: str) -> None:
    """Move a claim to a new status."""
    conn.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id))


def require_status(conn: sqlite3.Connection, claim_id: str, status: str) -> None:
    """Raise a 409 unless the claim is in the given status."""
    current = claim_status(conn, claim_id)
    if current != status:
        raise HTTPException(409, f"Claim {claim_id} is {current}, not {status}")


def approval_limit(conn: sqlite3.Connection) -> float:
    """Return the payout above which a handler must sign off."""
    return setting(conn, "company")["payout_approval_limit"]


def pay(conn: sqlite3.Connection, claim_id: str, amount: float, paid_by: str) -> None:
    """Record a payment and mark the claim decided."""
    conn.execute(
        "INSERT INTO payments VALUES (?, ?, ?, ?)", (claim_id, amount, paid_by, now())
    )
    set_status(conn, claim_id, "decided")


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: DB) -> dict[str, Any]:
    """Start work on a waiting claim."""
    require_status(conn, claim_id, "waiting")
    set_status(conn, claim_id, "in_progress")
    conn.commit()
    return get_claim(claim_id, conn)


def add_step(conn: sqlite3.Connection, claim_id: str, kind: str, text: str) -> None:
    """Add one step to a claim's activity."""
    conn.execute(
        "INSERT INTO steps (claim_id, kind, text, at) VALUES (?, ?, ?, ?)",
        (claim_id, kind, text, now()),
    )


@app.post("/api/claims/{claim_id}/release", operation_id="release_claim")
def release_claim(claim_id: str, release: Release, conn: DB) -> dict[str, Any]:
    """Put a claim that failed before its decision back in the queue."""
    require_status(conn, claim_id, "in_progress")
    attempts = claim_row(conn, claim_id)["attempts"] + release.counts_as_attempt
    status = "needs_handler" if attempts >= MAX_ATTEMPTS else "waiting"
    conn.execute(
        "UPDATE claims SET status = ?, attempts = ? WHERE claim_id = ?",
        (status, attempts, claim_id),
    )
    add_step(conn, claim_id, "error", release.reason)
    conn.commit()
    return get_claim(claim_id, conn)


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, step: Step, conn: DB) -> dict[str, str]:
    """Record one step of the agent's work on a claim."""
    claim_status(conn, claim_id)
    add_step(conn, claim_id, step.kind, step.text)
    conn.commit()
    return {"status": "recorded"}


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: DB) -> list[dict[str, Any]]:
    """List the steps of the agent's work on a claim, in order."""
    claim_status(conn, claim_id)
    rows = conn.execute(
        "SELECT step_id, kind, text, at FROM steps WHERE claim_id = ? ORDER BY step_id",
        (claim_id,),
    )
    return [dict(row) for row in rows]


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: DB) -> dict[str, Any]:
    """Record the decision on a claim in progress."""
    require_status(conn, claim_id, "in_progress")
    payout = round(decision.payout, 2)
    if decision.decision != "approve" and payout != 0:
        raise HTTPException(409, "A decline or a referral has a payout of 0")
    conn.execute(
        "INSERT INTO decisions (claim_id, decision, payout, reasons, "
        "policy_section, decided_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            claim_id,
            decision.decision,
            payout,
            decision.reasons,
            decision.policy_section,
            now(),
        ),
    )
    over_limit = decision.decision == "approve" and payout > approval_limit(conn)
    set_status(conn, claim_id, "awaiting_signoff" if over_limit else "decided")
    conn.commit()
    return get_claim(claim_id, conn)


@app.post("/api/claims/{claim_id}/payments", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: DB) -> dict[str, Any]:
    """Pay an approved claim its payout, once any sign-off it needs is given."""
    claim = get_claim(claim_id, conn)
    decision = claim["decision"]
    if decision is None or decision["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} is not approved")
    if claim["payment"] is not None:
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    if round(payment.amount, 2) != decision["payout"]:
        raise HTTPException(
            409, f"The amount must be the approved payout of {decision['payout']:.2f}"
        )
    if claim["status"] == "awaiting_signoff":
        raise HTTPException(
            409,
            f"A payout over {approval_limit(conn):,.2f} waits for a handler's sign-off",
        )
    pay(conn, claim_id, decision["payout"], "UnderCover Agent")
    conn.commit()
    return get_claim(claim_id, conn)


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off")
def sign_off(claim_id: str, sign: SignOff, conn: DB) -> dict[str, Any]:
    """Sign off an approved payout over the limit, which pays it."""
    require_status(conn, claim_id, "awaiting_signoff")
    fetch(conn, "handlers", "handler_id", sign.handler_id)
    conn.execute(
        "UPDATE decisions SET signed_off_by = ?, signed_off_at = ? WHERE claim_id = ?",
        (sign.handler_id, now(), claim_id),
    )
    payout = get_claim(claim_id, conn)["decision"]["payout"]
    pay(conn, claim_id, payout, sign.handler_id)
    conn.commit()
    return get_claim(claim_id, conn)


def run_record(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    """Return one run with its to-do list, or raise a 404."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"No run {run_id}")
    return {**dict(row), "todos": json.loads(row["todos"])}


@app.post("/api/runs", operation_id="start_run")
def start_run(start: RunStart, conn: DB) -> dict[str, Any]:
    """Start a run of the queue, capped at a number of claims."""
    cursor = conn.execute(
        "INSERT INTO runs (claim_limit, status, todos, summary, started_at) "
        "VALUES (?, 'running', '[]', '', ?)",
        (start.claim_limit, now()),
    )
    conn.commit()
    return run_record(conn, cursor.lastrowid or 0)


@app.get("/api/runs/latest", operation_id="get_latest_run")
def get_latest_run(conn: DB) -> dict[str, Any]:
    """Get the most recent run with its to-do list."""
    row = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()
    if row[0] is None:
        raise HTTPException(404, "No run yet")
    return run_record(conn, row[0])


@app.put("/api/runs/{run_id}/todos", operation_id="update_todos")
def update_todos(run_id: int, todos: list[Todo], conn: DB) -> dict[str, Any]:
    """Replace a run's to-do list."""
    run_record(conn, run_id)
    conn.execute(
        "UPDATE runs SET todos = ? WHERE run_id = ?",
        (json.dumps([t.model_dump() for t in todos]), run_id),
    )
    conn.commit()
    return run_record(conn, run_id)


@app.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, finish: RunFinish, conn: DB) -> dict[str, Any]:
    """Finish a run with a summary for the handlers."""
    run_record(conn, run_id)
    conn.execute(
        "UPDATE runs SET status = 'finished', summary = ?, finished_at = ? "
        "WHERE run_id = ?",
        (finish.summary, now(), run_id),
    )
    conn.commit()
    return run_record(conn, run_id)

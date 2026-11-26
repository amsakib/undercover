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

INSTRUCTIONS = Path(__file__).parent / "instructions.md"

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


def claim_status(conn: sqlite3.Connection, claim_id: str) -> str:
    """Return a claim's status, or raise a 404."""
    row = conn.execute(
        "SELECT status FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No claim_id {claim_id}")
    return row["status"]


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(conn: DB) -> list[dict[str, Any]]:
    """List the claims queue in order, with each claim's status."""
    rows = conn.execute("SELECT status, data FROM claims ORDER BY position")
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
    return {
        **claim,
        "status": claim_status(conn, claim_id),
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


@app.get("/api/policy-wording", operation_id="get_policy_wording")
def get_policy_wording(conn: DB) -> dict[str, str]:
    """Get the policy wording as markdown."""
    return {"text": setting(conn, "policy_wording")}


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Get the UnderCover Agent's instructions as markdown."""
    return {"text": INSTRUCTIONS.read_text(encoding="utf-8")}


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(conn: DB) -> list[dict[str, Any]]:
    """List the claims handlers."""
    rows = conn.execute("SELECT data FROM handlers ORDER BY handler_id")
    return [json.loads(row["data"]) for row in rows]


class Step(BaseModel):
    kind: Literal["tool_call", "tool_result", "message"]
    text: str


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


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, step: Step, conn: DB) -> dict[str, str]:
    """Record one step of the agent's work on a claim."""
    claim_status(conn, claim_id)
    conn.execute(
        "INSERT INTO steps (claim_id, kind, text, at) VALUES (?, ?, ?, ?)",
        (claim_id, step.kind, step.text, now()),
    )
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

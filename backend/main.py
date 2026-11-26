"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException

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

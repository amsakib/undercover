"""The claims queue and each claim's lifecycle: start, steps, release, decision,
payment and sign-off."""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import DB, fetch, now, setting
from backend.schemas import Decision, Payment, Release, SignOff, Step

MAX_ATTEMPTS = 2

router = APIRouter(prefix="/api/claims")


def claim_row(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return a claim's status and attempts, or raise a 404."""
    row = conn.execute(
        "SELECT status, attempts FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No claim_id {claim_id}")
    return row


def require_status(conn: sqlite3.Connection, claim_id: str, status: str) -> None:
    """Raise a 409 unless the claim is in the given status."""
    current = claim_row(conn, claim_id)["status"]
    if current != status:
        raise HTTPException(409, f"Claim {claim_id} is {current}, not {status}")


def set_status(conn: sqlite3.Connection, claim_id: str, status: str) -> None:
    """Move a claim to a new status."""
    conn.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id))


def add_step(conn: sqlite3.Connection, claim_id: str, kind: str, text: str) -> None:
    """Add one step to a claim's activity."""
    conn.execute(
        "INSERT INTO steps (claim_id, kind, text, at) VALUES (?, ?, ?, ?)",
        (claim_id, kind, text, now()),
    )


def approval_limit(conn: sqlite3.Connection) -> float:
    """Return the payout above which a handler must sign off."""
    return setting(conn, "company")["payout_approval_limit"]


def pay(conn: sqlite3.Connection, claim_id: str, amount: float, paid_by: str) -> None:
    """Record a payment and mark the claim decided."""
    conn.execute(
        "INSERT INTO payments VALUES (?, ?, ?, ?)", (claim_id, amount, paid_by, now())
    )
    set_status(conn, claim_id, "decided")


@router.get("", operation_id="list_claims")
def list_claims(conn: DB) -> list[dict[str, Any]]:
    """List the claims queue in order: each claim's status, the customer's name
    for the handlers, and the decision once there is one."""
    rows = conn.execute(
        "SELECT c.status, c.attempts, c.data, cu.data AS customer, d.decision, "
        "d.payout FROM claims c "
        "JOIN customers cu ON cu.customer_id = json_extract(c.data, '$.customer_id') "
        "LEFT JOIN decisions d ON d.claim_id = c.claim_id ORDER BY c.position"
    )
    fields = ("claim_id", "claim_type", "summary", "submitted_on", "amount_claimed")
    claims = []
    for row in rows:
        data = json.loads(row["data"])
        decision = (
            {"decision": row["decision"], "payout": row["payout"]}
            if row["decision"]
            else None
        )
        claims.append(
            {k: data[k] for k in fields}
            | {
                "customer_name": json.loads(row["customer"])["name"],
                "status": row["status"],
                "attempts": row["attempts"],
                "decision": decision,
            }
        )
    return claims


@router.get("/{claim_id}", operation_id="get_claim")
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


@router.post("/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: DB) -> dict[str, Any]:
    """Start work on a waiting claim."""
    require_status(conn, claim_id, "waiting")
    set_status(conn, claim_id, "in_progress")
    conn.commit()
    return get_claim(claim_id, conn)


@router.post("/{claim_id}/release", operation_id="release_claim")
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


@router.post("/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, step: Step, conn: DB) -> dict[str, str]:
    """Record one step of the agent's work on a claim."""
    claim_row(conn, claim_id)
    add_step(conn, claim_id, step.kind, step.text)
    conn.commit()
    return {"status": "recorded"}


@router.get("/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: DB) -> list[dict[str, Any]]:
    """List the steps of the agent's work on a claim, in order."""
    claim_row(conn, claim_id)
    rows = conn.execute(
        "SELECT step_id, kind, text, at FROM steps WHERE claim_id = ? ORDER BY step_id",
        (claim_id,),
    )
    return [dict(row) for row in rows]


@router.post("/{claim_id}/decision", operation_id="record_decision")
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


@router.post("/{claim_id}/payments", operation_id="pay_claim")
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


@router.post("/{claim_id}/sign-off", operation_id="sign_off")
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

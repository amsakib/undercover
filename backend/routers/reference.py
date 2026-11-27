"""The records the agent decides from: policies, claim history, plans, handlers
and the agent's instructions."""

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter

from backend.db import DB, fetch, setting

INSTRUCTIONS = Path(__file__).parent.parent / "instructions"

router = APIRouter(prefix="/api")


@router.get("/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, conn: DB) -> dict[str, Any]:
    """Get one policy."""
    return fetch(conn, "policies", "policy_id", policy_id)


@router.get("/customers/{customer_id}/claim-history", operation_id="get_claim_history")
def get_claim_history(customer_id: str, conn: DB) -> list[dict[str, Any]]:
    """Get a customer's earlier claims, without their personal details."""
    return fetch(conn, "customers", "customer_id", customer_id)["previous_claims"]


@router.get("/plans/{plan}", operation_id="get_plan")
def get_plan(plan: str, conn: DB) -> dict[str, Any]:
    """Get one plan's limits, with the add-ons and where the deductible applies."""
    return {
        **fetch(conn, "plans", "plan", plan),
        "deductible_applies_to": setting(conn, "deductible_applies_to"),
        "add_ons": setting(conn, "add_ons"),
    }


@router.get("/handlers", operation_id="list_handlers")
def list_handlers(conn: DB) -> list[dict[str, Any]]:
    """List the claims handlers."""
    rows = conn.execute("SELECT data FROM handlers ORDER BY handler_id")
    return [json.loads(row["data"]) for row in rows]


@router.get("/instructions/{name}", operation_id="get_instructions")
def get_instructions(name: Literal["queue", "claim"]) -> dict[str, str]:
    """Get the agent's instructions for running the queue or working a claim."""
    return {"text": (INSTRUCTIONS / f"{name}.md").read_text(encoding="utf-8")}

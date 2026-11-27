"""Every call the agent makes to the UnderCover backend."""

from typing import Any, Literal

import httpx

BACKEND_URL = "http://localhost:8000/api"

Document = Literal["wording", "manual"]

client = httpx.Client(base_url=BACKEND_URL, timeout=30)


class Refused(Exception):
    """The backend refused a request, such as a payment that waits for sign-off."""


def request(method: str, path: str, **kwargs: Any) -> Any:
    """Send one request and return its JSON, or raise Refused with the reason."""
    response = client.request(method, path, **kwargs)
    if response.is_error:
        raise Refused(f"Refused ({response.status_code}): {response.json()['detail']}")
    return response.json()


def claims() -> list[dict[str, Any]]:
    return request("GET", "/claims")


def claim(claim_id: str) -> dict[str, Any]:
    return request("GET", f"/claims/{claim_id}")


def policy(policy_id: str) -> dict[str, Any]:
    return request("GET", f"/policies/{policy_id}")


def claim_history(customer_id: str) -> list[dict[str, Any]]:
    return request("GET", f"/customers/{customer_id}/claim-history")


def plan(name: str) -> dict[str, Any]:
    return request("GET", f"/plans/{name}")


def contents(document: Document) -> dict[str, Any]:
    return request("GET", f"/documents/{document}")


def section(document: Document, number: str) -> dict[str, str]:
    return request("GET", f"/documents/{document}/sections/{number}")


def search(query: str) -> list[dict[str, str]]:
    return request("GET", "/documents/search", params={"query": query})


def instructions(name: Literal["queue", "claim"]) -> str:
    return request("GET", f"/instructions/{name}")["text"]


def start_claim(claim_id: str) -> dict[str, Any]:
    return request("POST", f"/claims/{claim_id}/start")


def record_step(claim_id: str, kind: str, text: str) -> None:
    request("POST", f"/claims/{claim_id}/steps", json={"kind": kind, "text": text})


def release(claim_id: str, reason: str, counts_as_attempt: bool) -> dict[str, Any]:
    return request(
        "POST",
        f"/claims/{claim_id}/release",
        json={"reason": reason, "counts_as_attempt": counts_as_attempt},
    )


def record_decision(claim_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    return request("POST", f"/claims/{claim_id}/decision", json=decision)


def pay(claim_id: str, amount: float) -> dict[str, Any]:
    return request("POST", f"/claims/{claim_id}/payments", json={"amount": amount})


def start_run(claim_limit: int) -> dict[str, Any]:
    return request("POST", "/runs", json={"claim_limit": claim_limit})


def run(run_id: int) -> dict[str, Any]:
    return request("GET", f"/runs/{run_id}")


def save_todos(run_id: int, todos: list[dict[str, Any]]) -> dict[str, Any]:
    return request("PUT", f"/runs/{run_id}/todos", json=todos)


def finish_run(run_id: int, summary: str) -> dict[str, Any]:
    return request("POST", f"/runs/{run_id}/finish", json={"summary": summary})

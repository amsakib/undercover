"""Work the claims queue: `uv run -m agent` or `uv run -m agent CLM-1001`."""

import sys
from uuid import uuid4

from agent import main as agent


def waiting_claims() -> list[str]:
    """Return the ids of the waiting claims, in queue order."""
    with agent.backend() as client:
        claims = client.get("/api/claims").raise_for_status().json()
    return [c["claim_id"] for c in claims if c["status"] == "waiting"]


def summary(claim_id: str) -> str:
    """Return one line on where a claim ended up."""
    with agent.backend() as client:
        claim = client.get(f"/api/claims/{claim_id}").raise_for_status().json()
    decision = claim["decision"]
    if decision is None:
        return f"{claim_id}  no decision  {claim['status']}"
    return (
        f"{claim_id}  {decision['decision']}  ${decision['payout']:,.2f}  "
        f"{claim['status']}"
    )


def main(claim_ids: list[str]) -> None:
    """Work the given claims, or every waiting claim in queue order."""
    for claim_id in claim_ids or waiting_claims():
        agent.run(claim_id, str(uuid4()))
        print(summary(claim_id))


if __name__ == "__main__":
    main(sys.argv[1:])

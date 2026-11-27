"""The UnderCover Agent's tools: the claim agent's and the queue agent's.

Each agent gets its run's state from its context: the claim agent's tools act only
on the claim it was given, and the queue agent's tools enforce the run's cap.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel

from agent import api

DOCUMENT_NAMES = {"wording": "Policy wording", "manual": "Claims manual"}
TODO_FOR_STATUS = {
    "decided": "done",
    "awaiting_signoff": "done",
    "needs_handler": "handler",
    "waiting": "todo, to try again",
}


@dataclass
class ClaimContext:
    """The one claim a claim agent works."""

    claim_id: str


@dataclass
class RunContext:
    """One run of the queue: its cap, the claims it started, and how it works one."""

    run_id: int
    claim_limit: int
    work: Callable[[str], str]
    started: list[str] = field(default_factory=list)
    finished: bool = False


class TodoItem(BaseModel):
    text: str
    status: Literal["todo", "in_progress", "done", "handler"]
    claim_id: str | None


@tool
def get_claim(runtime: ToolRuntime[ClaimContext]) -> dict[str, Any]:
    """Get the claim you are deciding: the story, the items and the documents."""
    return api.claim(runtime.context.claim_id)


@tool
def get_policy(policy_id: str) -> dict[str, Any]:
    """Get the customer's policy: the plan, add-ons, trip dates and travelers."""
    return api.policy(policy_id)


@tool
def get_claim_history(customer_id: str) -> list[dict[str, Any]]:
    """Get the customer's earlier claims."""
    return api.claim_history(customer_id)


@tool
def get_plan(plan: str) -> dict[str, Any]:
    """Get a plan's limits, the add-ons and where the deductible applies."""
    return api.plan(plan)


@tool
def get_contents(document: api.Document) -> dict[str, Any]:
    """List the sections of the policy wording or the claims manual."""
    return api.contents(document)


@tool
def get_section(
    document: api.Document, section: str, runtime: ToolRuntime[ClaimContext]
) -> dict[str, str]:
    """Read one numbered section of the policy wording or the claims manual."""
    found = api.section(document, section)
    read = f"{DOCUMENT_NAMES[document]} {found['section']}. {found['title']}"
    api.record_step(runtime.context.claim_id, "read", read)
    return found


@tool
def search_documents(query: str) -> list[dict[str, str]]:
    """Find the sections of the wording and the manual that mention every word."""
    return api.search(query)


@tool
def record_decision(
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    reasons: str,
    policy_section: str,
    runtime: ToolRuntime[ClaimContext],
) -> dict[str, Any]:
    """Record the decision, the payout in US dollars, the reasons and the section."""
    return api.record_decision(
        runtime.context.claim_id,
        {
            "decision": decision,
            "payout": payout,
            "reasons": reasons,
            "policy_section": policy_section,
        },
    )


@tool
def pay_claim(amount: float, runtime: ToolRuntime[ClaimContext]) -> dict[str, Any]:
    """Pay the approved claim its payout in US dollars."""
    return api.pay(runtime.context.claim_id, amount)


CLAIM_TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    get_plan,
    get_contents,
    get_section,
    search_documents,
    record_decision,
    pay_claim,
]


def waiting_claims() -> list[dict[str, Any]]:
    """Return the claims waiting in the queue, oldest in the queue first."""
    return [c for c in api.claims() if c["status"] == "waiting"]


def missed_claims(run: RunContext) -> list[str]:
    """Return the waiting claims this run should still work within its cap."""
    waiting = [c["claim_id"] for c in waiting_claims()]
    back = [c for c in run.started if c in waiting]
    room = run.claim_limit - len(run.started)
    return back + [c for c in waiting if c not in run.started][: max(room, 0)]


@tool
def list_waiting_claims(runtime: ToolRuntime[RunContext]) -> dict[str, Any]:
    """List the waiting claims and how many more claims this run may start."""
    run = runtime.context
    fields = ("claim_id", "claim_type", "summary", "submitted_on", "amount_claimed")
    return {
        "may_start": run.claim_limit - len(run.started),
        "started_this_run": run.started,
        "waiting": [{k: c[k] for k in (*fields, "attempts")} for c in waiting_claims()],
    }


@tool
def update_todos(todos: list[TodoItem], runtime: ToolRuntime[RunContext]) -> str:
    """Replace the run's to-do list, which the handlers watch."""
    api.save_todos(runtime.context.run_id, [t.model_dump() for t in todos])
    return f"Saved {len(todos)} to-dos."


@tool
def work_claim(claim_id: str, runtime: ToolRuntime[RunContext]) -> str:
    """Hand one waiting claim to a fresh claim agent; returns one line."""
    run = runtime.context
    status = api.claim(claim_id)["status"]
    if status != "waiting":
        return f"{claim_id} is {status}, not waiting, so it was not worked"
    if claim_id not in run.started:
        if len(run.started) >= run.claim_limit:
            return (
                f"Refused: this run may start {run.claim_limit} claims and has "
                f"started them all, so {claim_id} stays waiting"
            )
        run.started.append(claim_id)
    line = run.work(claim_id)
    status = api.claim(claim_id)["status"]
    return f"{line}. Mark its to-do {TODO_FOR_STATUS[status]}."


@tool
def finish_run(summary: str, runtime: ToolRuntime[RunContext]) -> str:
    """Finish the run with a short summary for the handlers."""
    run = runtime.context
    missed = missed_claims(run)
    if missed:
        return (
            "Refused: these claims are waiting within this run's cap: "
            f"{', '.join(missed)}. Work them before you finish."
        )
    api.finish_run(run.run_id, summary)
    run.finished = True
    return "The run is finished."


QUEUE_TOOLS = [list_waiting_claims, update_todos, work_claim, finish_run]

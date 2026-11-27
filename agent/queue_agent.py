"""The queue agent: plans a run, hands each claim to a fresh claim agent, finishes."""

import json
from collections.abc import Callable
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from agent import main

MAX_NUDGES = 2
TODO_FOR_STATUS = {
    "decided": "done",
    "awaiting_signoff": "done",
    "needs_handler": "handler",
    "waiting": "todo, to try again",
}
ClaimModels = Callable[[str], BaseChatModel | None]


class TodoItem(BaseModel):
    text: str
    status: Literal["todo", "in_progress", "done", "handler"]
    claim_id: str | None


class Run:
    """One run of the queue: its cap and the claims it has started."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.run_id: int = record["run_id"]
        self.claim_limit: int = record["claim_limit"]
        self.started: list[str] = []
        self.finished = False


def claims() -> list[dict[str, Any]]:
    """Return the queue as the backend has it."""
    return main.get("/api/claims")


def release_stuck() -> list[str]:
    """Put back any claim an earlier run left in progress, without counting it."""
    stuck = [c["claim_id"] for c in claims() if c["status"] == "in_progress"]
    for claim_id in stuck:
        main.release(
            claim_id, "Left in progress by an earlier run that stopped.", False
        )
    return stuck


def missed_claims(run: Run) -> list[str]:
    """Return the waiting claims this run should still work within its cap."""
    waiting = [c["claim_id"] for c in claims() if c["status"] == "waiting"]
    back = [c for c in run.started if c in waiting]
    room = run.claim_limit - len(run.started)
    return back + [c for c in waiting if c not in run.started][: max(room, 0)]


def save_todos(run_id: int, todos: list[dict[str, Any]]) -> None:
    """Replace the run's to-do list in the backend."""
    with main.backend() as client:
        client.put(f"/api/runs/{run_id}/todos", json=todos).raise_for_status()


def close(run: Run, summary: str) -> dict[str, Any]:
    """Finish the run in the backend with a summary."""
    with main.backend() as client:
        response = client.post(
            f"/api/runs/{run.run_id}/finish", json={"summary": summary}
        )
    run.finished = True
    return response.raise_for_status().json()


def outcomes(run: Run) -> str:
    """One line on where each claim this run started ended up."""
    lines = []
    for claim_id in run.started:
        claim = main.get(f"/api/claims/{claim_id}")
        if claim["decision"]:
            lines.append(main.outcome(claim))
        else:
            lines.append(f"{claim_id} {claim['status'].replace('_', ' ')}")
    return "\n".join(lines)


def queue_tools(run: Run, claim_llm: ClaimModels) -> list[BaseTool]:
    """The queue agent's tools, bound to this run."""

    @tool
    def list_waiting_claims() -> str:
        """List the waiting claims and how many more claims this run may start."""
        waiting = [
            {k: c[k] for k in ("claim_id", "claim_type", "summary", "submitted_on")}
            | {"amount_claimed": c["amount_claimed"], "attempts": c["attempts"]}
            for c in claims()
            if c["status"] == "waiting"
        ]
        return json.dumps(
            {
                "may_start": run.claim_limit - len(run.started),
                "started_this_run": run.started,
                "waiting": waiting,
            }
        )

    @tool
    def update_todos(todos: list[TodoItem]) -> str:
        """Replace the run's to-do list, which the handlers watch."""
        save_todos(run.run_id, [t.model_dump() for t in todos])
        return f"Saved {len(todos)} to-dos."

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand one waiting claim to a fresh claim agent; returns one line."""
        status = main.get(f"/api/claims/{claim_id}")["status"]
        if status != "waiting":
            return f"{claim_id} is {status}, not waiting, so it was not worked"
        if claim_id not in run.started:
            if len(run.started) >= run.claim_limit:
                return (
                    f"Refused: this run may start {run.claim_limit} claims and has "
                    f"started them all, so {claim_id} stays waiting"
                )
            run.started.append(claim_id)
        line = main.work_claim(claim_id, claim_llm(claim_id))
        print(line, flush=True)
        status = main.get(f"/api/claims/{claim_id}")["status"]
        return f"{line}. Mark its to-do {TODO_FOR_STATUS[status]}."

    @tool
    def finish_run(summary: str) -> str:
        """Finish the run with a short summary for the handlers."""
        missed = missed_claims(run)
        if missed:
            return (
                "Refused: these claims are waiting within this run's cap: "
                f"{', '.join(missed)}. Work them before you finish."
            )
        close(run, summary)
        return "The run is finished."

    return [list_waiting_claims, update_todos, work_claim, finish_run]


def nudge(run: Run) -> str:
    """Tell the queue agent what it has left undone."""
    missed = missed_claims(run)
    if missed:
        return (
            f"You stopped before finishing. These claims are waiting within the "
            f"cap: {', '.join(missed)}. Work them, then call finish_run."
        )
    return "You stopped before finishing. Call finish_run with your summary."


def run_queue(
    claim_limit: int,
    llm: BaseChatModel | None = None,
    claim_llm: ClaimModels = lambda _: None,
) -> dict[str, Any]:
    """Work the queue, starting at most claim_limit claims, and return the run."""
    release_stuck()
    with main.backend() as client:
        instructions = client.get("/api/instructions/queue").raise_for_status().json()
        record = client.post("/api/runs", json={"claim_limit": claim_limit})
    run = Run(record.raise_for_status().json())
    agent = create_agent(
        llm or main.model(),
        tools=queue_tools(run, claim_llm),
        system_prompt=instructions["text"],
        middleware=main.retries(),
        checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": f"run-{run.run_id}"}}
    message = f"Please work the queue. This run may start up to {claim_limit} claims."
    try:
        for _ in range(MAX_NUDGES + 1):
            agent.invoke({"messages": [{"role": "user", "content": message}]}, config)
            if run.finished:
                return main.get("/api/runs/latest")
            message = nudge(run)
        reason = f"The queue agent stopped without finishing. {message}"
    except (main.RateLimitStop, ModelRateLimitError) as error:
        reason = f"Stopped by the model provider's rate limit: {error}"
    except Exception as error:  # noqa: BLE001 a failed run must still be closed
        reason = f"Stopped by an error: {type(error).__name__}: {error}"
    return close(run, f"{reason}\n{outcomes(run)}".strip())

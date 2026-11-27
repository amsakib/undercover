"""The harness: runs the agents, records their work, and recovers when they fail.

The claim agent decides one claim; `work_claim` gives each claim a fresh one and
puts the claim back in the queue if it fails. The queue agent plans the run and
hands claims to `work_claim`; `run_queue` nudges it when it stops early and always
closes the run.
"""

import json
import os
from collections.abc import Callable
from functools import cache
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    wrap_tool_call,
)
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.exceptions import ModelError, ModelRateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import SecretStr

from agent import api
from agent.tools import (
    CLAIM_TOOLS,
    QUEUE_TOOLS,
    ClaimContext,
    RunContext,
    missed_claims,
)

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MODEL_TIMEOUT = 120
MAX_MODEL_CALLS = 40
RETRIES = 2
RETRY_DELAY = 2.0
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_DELAY = 10.0
MAX_DELAY = 60.0
MAX_NUDGES = 2
STEP_TEXT_LIMIT = 1000
REASON_LIMIT = 200

ClaimModels = Callable[[str], BaseChatModel | None]


class RateLimitStop(Exception):
    """The model provider's rate limit outlasted the retries."""


@cache
def rate_limiter(requests_per_minute: float) -> InMemoryRateLimiter:
    """Return the one rate limiter that every agent in this process shares."""
    return InMemoryRateLimiter(requests_per_second=requests_per_minute / 60)


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    per_minute = os.getenv("MODEL_REQUESTS_PER_MINUTE")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=MODEL_TIMEOUT,
        max_retries=0,
        rate_limiter=rate_limiter(float(per_minute)) if per_minute else None,
    )


def rate_limited(error: Exception) -> bool:
    """Whether the model provider refused a request for its rate limit."""
    return isinstance(error, ModelRateLimitError)


def retryable(error: Exception) -> bool:
    """Whether another error from the model provider is worth retrying."""
    if isinstance(error, ModelError):
        return error.is_retryable and not rate_limited(error)
    return True


class RateLimitRetryMiddleware(ModelRetryMiddleware):
    """Retries the model after a rate limit, with its own longer backoff."""


@wrap_tool_call
def backend_refusals(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Show the agent why the backend refused a tool call, so it can carry on."""
    try:
        return handler(request)
    except api.Refused as refusal:
        call = request.tool_call
        return ToolMessage(str(refusal), tool_call_id=call["id"], name=call["name"])


def middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    """Retry the model, rate limits with a longer backoff, and show refusals."""
    return [
        RateLimitRetryMiddleware(
            max_retries=RATE_LIMIT_RETRIES,
            retry_on=rate_limited,
            on_failure="error",
            initial_delay=RATE_LIMIT_DELAY,
            max_delay=MAX_DELAY,
        ),
        ModelRetryMiddleware(
            max_retries=RETRIES,
            retry_on=retryable,
            on_failure="error",
            initial_delay=RETRY_DELAY,
            max_delay=MAX_DELAY,
        ),
        backend_refusals,
    ]


def steps(message: BaseMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent into the steps the dashboard shows."""
    if isinstance(message, ToolMessage):
        text = message.text
        if len(text) > STEP_TEXT_LIMIT:
            text = text[:STEP_TEXT_LIMIT] + "..."
        return [("tool_result", f"{message.name}: {text}")]
    found: list[tuple[str, str]] = []
    if message.text:
        found.append(("message", str(message.text)))
    if isinstance(message, AIMessage):
        found.extend(
            ("tool_call", f"{c['name']} {json.dumps(c['args'])}")
            for c in message.tool_calls
        )
    return found


def run_claim_agent(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Run a fresh claim agent on one claim and return its last reply."""
    agent = create_agent(
        llm or model(),
        tools=CLAIM_TOOLS,
        system_prompt=api.instructions("claim"),
        middleware=[
            *middleware(),
            ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="error"),
        ],
        context_schema=ClaimContext,
    )
    api.start_claim(claim_id)
    reply = ""
    for update in agent.stream(
        {"messages": [{"role": "user", "content": f"Please decide {claim_id}."}]},
        {"configurable": {"thread_id": str(uuid4())}},
        context=ClaimContext(claim_id),
        stream_mode="updates",
    ):
        for node in update.values():
            for message in (node or {}).get("messages", []):
                for kind, text in steps(message):
                    api.record_step(claim_id, kind, text)
                reply = message.text
    return reply


def outcome(claim: dict[str, Any]) -> str:
    """Return one line on a claim that has a decision."""
    decision = claim["decision"]
    where = {"decided": "decided", "awaiting_signoff": "waiting for sign-off"}
    return (
        f"{claim['claim_id']} {decision['decision']} ${decision['payout']:,.2f} "
        f"{where[claim['status']]}"
    )


def failure(claim: dict[str, Any], reason: str) -> str:
    """Return one line on a claim that failed and was released."""
    if claim["status"] == "needs_handler":
        return (
            f"{claim['claim_id']} failed ({reason}), left for a handler after "
            f"{claim['attempts']} attempts"
        )
    return (
        f"{claim['claim_id']} failed ({reason}), back in the queue "
        f"(attempt {claim['attempts']})"
    )


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim with a fresh claim agent and report back in one line.

    A claim that fails before it is decided goes back in the queue. A rate limit
    that outlasts the retries puts it back without counting an attempt and raises
    RateLimitStop, so the run stops instead of failing every claim after it.
    """
    status = api.claim(claim_id)["status"]
    if status != "waiting":
        return f"{claim_id} is {status}, not waiting, so it was not worked"
    try:
        run_claim_agent(claim_id, llm)
        reason = "the agent finished without recording a decision"
    except ModelRateLimitError as error:
        reason = f"the model provider's rate limit: {error}"[:REASON_LIMIT]
        if api.claim(claim_id)["status"] == "in_progress":
            api.release(claim_id, reason, counts_as_attempt=False)
        raise RateLimitStop(
            f"{claim_id} stopped by the model provider's rate limit, back in the "
            "queue (no attempt counted)"
        ) from error
    except Exception as error:  # noqa: BLE001 any failure must release the claim
        reason = f"{type(error).__name__}: {error}"[:REASON_LIMIT]
    claim = api.claim(claim_id)
    if claim["status"] == "in_progress":
        return failure(api.release(claim_id, reason, counts_as_attempt=True), reason)
    if claim["decision"] is None:
        return f"{claim_id} failed before it started ({reason}), still {status}"
    return outcome(claim)


def release_stuck() -> None:
    """Put back any claim an earlier run left in progress, without counting it."""
    for claim in api.claims():
        if claim["status"] == "in_progress":
            api.release(
                claim["claim_id"],
                "Left in progress by an earlier run that stopped.",
                counts_as_attempt=False,
            )


def nudge(run: RunContext) -> str:
    """Tell the queue agent what it has left undone."""
    missed = missed_claims(run)
    if missed:
        return (
            f"You stopped before finishing. These claims are waiting within the "
            f"cap: {', '.join(missed)}. Work them, then call finish_run."
        )
    return "You stopped before finishing. Call finish_run with your summary."


def supervise(llm: BaseChatModel | None, run: RunContext) -> str | None:
    """Run the queue agent, nudging it when it stops early.

    Return None once it has finished the run, or why it stopped without finishing.
    """
    agent = create_agent(
        llm or model(),
        tools=QUEUE_TOOLS,
        system_prompt=api.instructions("queue"),
        middleware=middleware(),
        context_schema=RunContext,
        checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": f"run-{run.run_id}"}}
    message = (
        f"Please work the queue. This run may start up to {run.claim_limit} claims."
    )
    for _ in range(MAX_NUDGES + 1):
        agent.invoke(
            {"messages": [{"role": "user", "content": message}]}, config, context=run
        )
        if run.finished:
            return None
        message = nudge(run)
    return f"The queue agent stopped without finishing. {message}"


def outcomes(run: RunContext) -> str:
    """One line on where each claim this run started ended up."""
    lines = []
    for claim_id in run.started:
        claim = api.claim(claim_id)
        if claim["decision"]:
            lines.append(outcome(claim))
        else:
            lines.append(f"{claim_id} {claim['status'].replace('_', ' ')}")
    return "\n".join(lines)


def run_queue(
    claim_limit: int,
    llm: BaseChatModel | None = None,
    claim_llm: ClaimModels = lambda _: None,
) -> dict[str, Any]:
    """Work the queue, starting at most claim_limit claims, and return the run.

    However the queue agent stops, the run is closed with a summary.
    """

    def work(claim_id: str) -> str:
        line = work_claim(claim_id, claim_llm(claim_id))
        print(line, flush=True)
        return line

    release_stuck()
    run = RunContext(api.start_run(claim_limit)["run_id"], claim_limit, work)
    try:
        reason = supervise(llm, run)
    except (RateLimitStop, ModelRateLimitError) as error:
        reason = f"Stopped by the model provider's rate limit: {error}"
    except Exception as error:  # noqa: BLE001 a failed run must still be closed
        reason = f"Stopped by an error: {type(error).__name__}: {error}"
    if reason is None:
        return api.run(run.run_id)
    return api.finish_run(run.run_id, f"{reason}\n{outcomes(run)}".strip())

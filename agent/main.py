"""The UnderCover Agent: the claim agent that decides one claim."""

import json
import os
from functools import cache
from typing import Any, Literal
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.exceptions import ModelError, ModelRateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

load_dotenv(override=True)

BACKEND_URL = "http://localhost:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MODEL_TIMEOUT = 120
MAX_MODEL_CALLS = 40
RETRIES = 2
RETRY_DELAY = 2.0
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_DELAY = 10.0
MAX_DELAY = 60.0
MAX_ATTEMPTS = 2
STEP_TEXT_LIMIT = 1000
REASON_LIMIT = 200
DOCUMENT_NAMES = {"wording": "Policy wording", "manual": "Claims manual"}


class RateLimitStop(Exception):
    """The model provider's rate limit outlasted the retries."""


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def call(
    method: str,
    path: str,
    body: Any = None,
    params: dict[str, str] | None = None,
) -> str:
    """Call the backend and return the response, or the reason it refused."""
    with backend() as client:
        response = client.request(method, path, json=body, params=params)
    if response.is_error:
        return f"Refused ({response.status_code}): {response.json()['detail']}"
    return response.text


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim in full: the story, the items claimed and the documents."""
    return call("GET", f"/api/claims/{claim_id}")


@tool
def get_policy(policy_id: str) -> str:
    """Get the customer's policy: the plan, add-ons, trip dates and travelers."""
    return call("GET", f"/api/policies/{policy_id}")


@tool
def get_claim_history(customer_id: str) -> str:
    """Get the customer's earlier claims."""
    return call("GET", f"/api/customers/{customer_id}/claim-history")


@tool
def get_plan(plan: str) -> str:
    """Get a plan's limits, the add-ons and where the deductible applies."""
    return call("GET", f"/api/plans/{plan}")


@tool
def get_contents(document: Literal["wording", "manual"]) -> str:
    """List the sections of the policy wording or the claims manual."""
    return call("GET", f"/api/documents/{document}")


@tool
def get_section(document: Literal["wording", "manual"], section: str) -> str:
    """Read one numbered section of the policy wording or the claims manual."""
    return call("GET", f"/api/documents/{document}/sections/{section}")


@tool
def search_documents(query: str) -> str:
    """Find the sections of the wording and the manual that mention every word."""
    return call("GET", "/api/documents/search", params={"query": query})


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    reasons: str,
    policy_section: str,
) -> str:
    """Record the decision, the payout in US dollars, the reasons and the section."""
    return call(
        "POST",
        f"/api/claims/{claim_id}/decision",
        {
            "decision": decision,
            "payout": payout,
            "reasons": reasons,
            "policy_section": policy_section,
        },
    )


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay an approved claim its payout in US dollars."""
    return call("POST", f"/api/claims/{claim_id}/payments", {"amount": amount})


TOOLS = [
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


def retries() -> list[ModelRetryMiddleware]:
    """Retry rate limits with a long backoff and other provider errors briefly."""
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
    ]


def middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    """The claim agent's retries and its limit on model calls."""
    return [
        *retries(),
        ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="error"),
    ]


def read_step(message: ToolMessage) -> list[dict[str, str]]:
    """Name the section of a document the agent read, if it read one."""
    if message.name != "get_section" or message.text.startswith("Refused"):
        return []
    section = json.loads(message.text)
    name = DOCUMENT_NAMES[section["document"]]
    return [
        {
            "kind": "read",
            "text": f"{name} {section['section']}. {section['title']}",
        }
    ]


def steps(message: BaseMessage) -> list[dict[str, str]]:
    """Turn one message from the agent into the steps the dashboard shows."""
    if isinstance(message, ToolMessage):
        text = message.text
        if len(text) > STEP_TEXT_LIMIT:
            text = text[:STEP_TEXT_LIMIT] + "..."
        return [
            {"kind": "tool_result", "text": f"{message.name}: {text}"},
            *read_step(message),
        ]
    found = []
    if message.text:
        found.append({"kind": "message", "text": message.text})
    if isinstance(message, AIMessage):
        found.extend(
            {"kind": "tool_call", "text": f"{c['name']} {json.dumps(c['args'])}"}
            for c in message.tool_calls
        )
    return found


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the claim agent on one claim and return its final reply."""
    with backend() as client:
        instructions = client.get("/api/instructions/claim").raise_for_status().json()
        agent = create_agent(
            llm or model(),
            tools=TOOLS,
            system_prompt=instructions["text"],
            middleware=middleware(),
        )
        client.post(f"/api/claims/{claim_id}/start").raise_for_status()
        reply = ""
        for update in agent.stream(
            {"messages": [{"role": "user", "content": f"Please decide {claim_id}."}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="updates",
        ):
            for node in update.values():
                for message in (node or {}).get("messages", []):
                    for step in steps(message):
                        client.post(f"/api/claims/{claim_id}/steps", json=step)
                    reply = message.text
    return reply


def get(path: str) -> Any:
    """Read one record from the backend."""
    with backend() as client:
        return client.get(path).raise_for_status().json()


def release(claim_id: str, reason: str, counts_as_attempt: bool) -> dict[str, Any]:
    """Put a claim that failed before its decision back in the queue."""
    with backend() as client:
        response = client.post(
            f"/api/claims/{claim_id}/release",
            json={"reason": reason, "counts_as_attempt": counts_as_attempt},
        )
    return response.raise_for_status().json()


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
        f"(attempt {claim['attempts']} of {MAX_ATTEMPTS})"
    )


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim with a fresh claim agent and report back in one line.

    A claim that fails before it is decided goes back in the queue. A rate limit
    that outlasts the retries puts it back without counting an attempt and raises
    RateLimitStop, so the run stops instead of failing every claim after it.
    """
    status = get(f"/api/claims/{claim_id}")["status"]
    if status != "waiting":
        return f"{claim_id} is {status}, not waiting, so it was not worked"
    try:
        run(claim_id, str(uuid4()), llm)
        reason = "the agent finished without recording a decision"
    except ModelRateLimitError as error:
        reason = f"the model provider's rate limit: {error}"[:REASON_LIMIT]
        if get(f"/api/claims/{claim_id}")["status"] == "in_progress":
            release(claim_id, reason, counts_as_attempt=False)
        raise RateLimitStop(
            f"{claim_id} stopped by the model provider's rate limit, back in the "
            "queue (no attempt counted)"
        ) from error
    except Exception as error:  # noqa: BLE001 any failure must release the claim
        reason = f"{type(error).__name__}: {error}"[:REASON_LIMIT]
    claim = get(f"/api/claims/{claim_id}")
    if claim["status"] == "in_progress":
        return failure(release(claim_id, reason, counts_as_attempt=True), reason)
    if claim["decision"] is None:
        return f"{claim_id} failed before it started ({reason}), still {status}"
    return outcome(claim)

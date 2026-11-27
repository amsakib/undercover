"""The UnderCover Agent."""

import json
import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

load_dotenv(override=True)

BACKEND_URL = "http://localhost:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"
STEP_TEXT_LIMIT = 1000


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def call(method: str, path: str, body: dict[str, Any] | None = None) -> str:
    """Call the backend and return the response, or the reason it refused."""
    with backend() as client:
        response = client.request(method, path, json=body)
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
def get_policy_wording() -> str:
    """Get the policy wording, the contract every decision follows."""
    return call("GET", "/api/policy-wording")


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
    get_policy_wording,
    record_decision,
    pay_claim,
]


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or GPT-6 Luna by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


def steps(message: BaseMessage) -> list[dict[str, str]]:
    """Turn one message from the agent into the steps the dashboard shows."""
    if isinstance(message, ToolMessage):
        text = message.text
        if len(text) > STEP_TEXT_LIMIT:
            text = text[:STEP_TEXT_LIMIT] + "..."
        return [{"kind": "tool_result", "text": f"{message.name}: {text}"}]
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
    """Run the agent on one claim and return its final reply."""
    with backend() as client:
        instructions = client.get("/api/instructions/claim").raise_for_status().json()
        agent = create_agent(
            llm or model(), tools=TOOLS, system_prompt=instructions["text"]
        )
        client.post(f"/api/claims/{claim_id}/start").raise_for_status()
        reply = ""
        for update in agent.stream(
            {"messages": [{"role": "user", "content": f"Please decide {claim_id}."}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="updates",
        ):
            for node in update.values():
                for message in node["messages"]:
                    for step in steps(message):
                        client.post(f"/api/claims/{claim_id}/steps", json=step)
                    reply = message.text
    return reply

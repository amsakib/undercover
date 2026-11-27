"""Scripted models and helpers for the agent's tests. No test calls a model."""

from collections.abc import Iterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent import api


class StubModel(BaseChatModel):
    """A chat model that gives scripted replies, or raises a scripted error."""

    replies: Iterator[Any]

    @property
    def _llm_type(self):
        return "stub"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


def stub(*replies):
    return StubModel(replies=iter(replies))


def call(name, args=None, n="1"):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args or {}, "id": n}]
    )


def decision(kind, payout, n="2"):
    return call(
        "record_decision",
        {
            "decision": kind,
            "payout": payout,
            "reasons": "Covered by the wording.",
            "policy_section": "Section 3. Trip Delay",
        },
        n,
    )


def declines():
    return stub(decision("decline", 0), AIMessage(content="Declined."))


def claim(claim_id):
    return api.claim(claim_id)


def steps(claim_id):
    return api.request("GET", f"/claims/{claim_id}/steps")

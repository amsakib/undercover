"""The bodies the API accepts."""

from typing import Literal

from pydantic import BaseModel, Field


class Step(BaseModel):
    kind: Literal["tool_call", "tool_result", "message", "read", "error"]
    text: str


class Release(BaseModel):
    reason: str
    counts_as_attempt: bool


class Decision(BaseModel):
    decision: Literal["approve", "decline", "refer"]
    payout: float = Field(ge=0)
    reasons: str
    policy_section: str


class Payment(BaseModel):
    amount: float = Field(gt=0)


class SignOff(BaseModel):
    handler_id: str


class RunStart(BaseModel):
    claim_limit: int = Field(ge=1)


class Todo(BaseModel):
    text: str
    status: Literal["todo", "in_progress", "done", "handler"]
    claim_id: str | None


class RunFinish(BaseModel):
    summary: str

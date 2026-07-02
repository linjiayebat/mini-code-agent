from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StartRunRequest(WebModel):
    prompt: str = Field(min_length=1, max_length=20_000)


class ApprovalDecisionRequest(WebModel):
    approved: bool


class WebRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class WebEvent(WebModel):
    sequence: int = Field(ge=1)
    type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    payload: dict[str, Any] = Field(default_factory=dict)


class RunSnapshot(WebModel):
    run_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    status: WebRunStatus
    last_sequence: int = Field(default=0, ge=0)


class RunDetail(RunSnapshot):
    prompt: str = Field(min_length=1, max_length=20_000)
    final_text: str | None = Field(default=None, max_length=2_000_000)
    error: str | None = Field(default=None, max_length=500)

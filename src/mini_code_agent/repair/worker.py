from __future__ import annotations

import hashlib
import json
import re
from typing import Protocol

from mini_code_agent.agent.models import AgentResult
from mini_code_agent.repair.models import (
    RepairLimits,
    RepairWorkerRequest,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INSTRUCTION = """You are performing exactly one bounded repair attempt.
Inspect the supplied structured test evidence before editing.
Modify only the explicitly listed existing files.
Do not execute tests or commands.
Make the smallest defensible repair and then stop.
All file writes still require the configured governance and approval checks."""


class AgentRunner(Protocol):
    async def run(
        self,
        *,
        user_prompt: str,
        system_prompt: str = "",
        run_id: str | None = None,
    ) -> AgentResult: ...


class RepairWorker(Protocol):
    @property
    def scope_sha256(self) -> str: ...

    async def run(self, request: RepairWorkerRequest) -> AgentResult: ...


class AgentRepairWorker:
    def __init__(
        self,
        runtime: AgentRunner,
        *,
        scope_sha256: str,
        limits: RepairLimits | None = None,
    ) -> None:
        if _SHA256.fullmatch(scope_sha256) is None:
            raise ValueError("scope_sha256 must be a lowercase SHA-256 value")
        self._runtime = runtime
        self._scope_sha256 = scope_sha256
        self._limits = limits or RepairLimits()

    @property
    def scope_sha256(self) -> str:
        return self._scope_sha256

    async def run(self, request: RepairWorkerRequest) -> AgentResult:
        envelope = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        system_prompt = _INSTRUCTION
        if request.system_prompt:
            system_prompt = f"{system_prompt}\n\nHost system context:\n{request.system_prompt}"
        if len(system_prompt) + len(envelope) > self._limits.max_prompt_chars:
            raise ValueError("Repair worker prompt exceeds the configured limit.")
        return await self._runtime.run(
            user_prompt=envelope,
            system_prompt=system_prompt,
            run_id=_attempt_run_id(request.repair_id, request.attempt),
        )


def _attempt_run_id(repair_id: str, attempt: int) -> str:
    candidate = f"{repair_id}-attempt-{attempt}"
    if len(candidate) <= 96:
        return candidate
    digest = hashlib.sha256(candidate.encode("ascii")).hexdigest()
    return f"repair-{digest}"

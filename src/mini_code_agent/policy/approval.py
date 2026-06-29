from __future__ import annotations

from typing import Protocol

from mini_code_agent.policy.models import ApprovalRequest


class ApprovalHandler(Protocol):
    async def approve(self, request: ApprovalRequest) -> bool: ...


class DenyAllApprovalHandler:
    async def approve(self, request: ApprovalRequest) -> bool:
        del request
        return False


class StaticApprovalHandler:
    def __init__(self, *, approved: bool) -> None:
        self._approved = approved
        self.requests: list[ApprovalRequest] = []

    async def approve(self, request: ApprovalRequest) -> bool:
        self.requests.append(request)
        return self._approved

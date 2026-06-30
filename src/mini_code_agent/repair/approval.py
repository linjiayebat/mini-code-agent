from __future__ import annotations

from typing import Protocol

from mini_code_agent.repair.models import RepairPreview


class RepairApprovalHandler(Protocol):
    async def approve(self, preview: RepairPreview) -> bool: ...


class StaticRepairApprovalHandler:
    def __init__(self, *, approved: bool) -> None:
        self._approved = approved
        self.requests: list[RepairPreview] = []

    async def approve(self, preview: RepairPreview) -> bool:
        self.requests.append(preview)
        return self._approved


class DenyAllRepairApprovalHandler:
    def __init__(self) -> None:
        self.requests: list[RepairPreview] = []

    async def approve(self, preview: RepairPreview) -> bool:
        self.requests.append(preview)
        return False

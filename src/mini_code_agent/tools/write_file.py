from __future__ import annotations

import asyncio
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.policy.models import ActionPreview, RiskLevel
from mini_code_agent.tools._mutation import mutation_error, mutation_result
from mini_code_agent.tools.base import SideEffect, ToolDefinition
from mini_code_agent.workspace.boundary import WorkspaceBoundary
from mini_code_agent.workspace.errors import WorkspaceError
from mini_code_agent.workspace.models import MutationPreview, MutationResult

_MAX_TEXT_CHARS = 16 * 1024 * 1024
_MAX_APPROVAL_DIFF_CHARS = 32_768


class _WriteFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=_MAX_TEXT_CHARS)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


class WriteFileTool:
    _definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="write_file",
        description=(
            "Create a UTF-8 workspace file, or atomically replace an existing file "
            "when its SHA-256 matches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                "content": {"type": "string", "maxLength": _MAX_TEXT_CHARS},
                "expected_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["path", "content", "reason"],
            "additionalProperties": False,
        },
        side_effect=SideEffect.WRITE,
    )

    def __init__(self, workspace: WorkspaceBoundary) -> None:
        self._workspace = workspace

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def preview(self, call: ToolCall) -> ActionPreview:
        arguments = self._validate(call)
        preview = await asyncio.to_thread(self._preview_validated, arguments)
        return ActionPreview(
            tool_call_id=call.id,
            tool_name=self._definition.name,
            side_effect=self._definition.side_effect,
            risk=RiskLevel.HIGH,
            summary=(
                "Create a workspace file."
                if preview.created
                else "Atomically replace a workspace file."
            ),
            reason=arguments.reason,
            resources=(preview.path,),
            diff=preview.diff[:_MAX_APPROVAL_DIFF_CHARS],
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            arguments = self._validate(call)
        except (ValidationError, ValueError):
            return mutation_error(
                call.id,
                "invalid_arguments",
                "write_file arguments are invalid.",
            )
        try:
            result = await asyncio.to_thread(self._execute_validated, arguments)
        except WorkspaceError as exc:
            return mutation_error(call.id, exc.code.value, exc.public_message)
        return mutation_result(call.id, result)

    def _preview_validated(self, arguments: _WriteFileArguments) -> MutationPreview:
        return self._workspace.preview_write(
            arguments.path,
            arguments.content,
            expected_sha256=arguments.expected_sha256,
        )

    def _execute_validated(self, arguments: _WriteFileArguments) -> MutationResult:
        return self._workspace.apply_write(
            arguments.path,
            arguments.content,
            expected_sha256=arguments.expected_sha256,
        )

    def _validate(self, call: ToolCall) -> _WriteFileArguments:
        if call.name != self._definition.name:
            raise ValueError("Unexpected tool name.")
        return _WriteFileArguments.model_validate(call.model_dump(mode="json")["arguments"])

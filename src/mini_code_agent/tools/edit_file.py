from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.policy.models import ActionPreview, RiskLevel
from mini_code_agent.tools._mutation import mutation_error, mutation_result
from mini_code_agent.tools.base import SideEffect, ToolDefinition
from mini_code_agent.workspace.boundary import WorkspaceBoundary
from mini_code_agent.workspace.errors import WorkspaceError, WorkspaceErrorCode
from mini_code_agent.workspace.models import MutationPreview, MutationResult

_MAX_TEXT_CHARS = 16 * 1024 * 1024
_MAX_APPROVAL_DIFF_CHARS = 32_768


class _EditFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    old_text: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    new_text: str = Field(max_length=_MAX_TEXT_CHARS)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class _EditFailure(Exception):
    code: str
    public_message: str


class EditFileTool:
    _definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="edit_file",
        description=(
            "Replace exactly one text occurrence in a UTF-8 workspace file "
            "when its SHA-256 matches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                "old_text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _MAX_TEXT_CHARS,
                },
                "new_text": {"type": "string", "maxLength": _MAX_TEXT_CHARS},
                "expected_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": [
                "path",
                "old_text",
                "new_text",
                "expected_sha256",
                "reason",
            ],
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
            summary="Replace exactly one occurrence in a workspace file.",
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
                "edit_file arguments are invalid.",
            )
        try:
            result = await asyncio.to_thread(self._execute_validated, arguments)
        except WorkspaceError as exc:
            return mutation_error(call.id, exc.code.value, exc.public_message)
        except _EditFailure as exc:
            return mutation_error(call.id, exc.code, exc.public_message)
        return mutation_result(call.id, result)

    def _preview_validated(self, arguments: _EditFileArguments) -> MutationPreview:
        content = self._replacement_content(arguments)
        return self._workspace.preview_write(
            arguments.path,
            content,
            expected_sha256=arguments.expected_sha256,
        )

    def _execute_validated(self, arguments: _EditFileArguments) -> MutationResult:
        content = self._replacement_content(arguments)
        return self._workspace.apply_write(
            arguments.path,
            content,
            expected_sha256=arguments.expected_sha256,
        )

    def _replacement_content(self, arguments: _EditFileArguments) -> str:
        source = self._workspace.read_text(arguments.path)
        if source.sha256 != arguments.expected_sha256:
            raise WorkspaceError(
                WorkspaceErrorCode.CONFLICT,
                "Workspace file changed before the requested write.",
                retryable=True,
            )
        match_count = source.text.count(arguments.old_text)
        if match_count == 0:
            raise _EditFailure(
                "match_not_found",
                "Edit text was not found in the workspace file.",
            )
        if match_count > 1:
            raise _EditFailure(
                "match_not_unique",
                "Edit text matched more than once in the workspace file.",
            )
        content = source.text.replace(arguments.old_text, arguments.new_text, 1)
        if content == source.text:
            raise _EditFailure(
                "no_change",
                "Edit would not change the workspace file.",
            )
        return content

    def _validate(self, call: ToolCall) -> _EditFileArguments:
        if call.name != self._definition.name:
            raise ValueError("Unexpected tool name.")
        return _EditFileArguments.model_validate(call.model_dump(mode="json")["arguments"])

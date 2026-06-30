from __future__ import annotations

import asyncio
import json
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.skills.catalog import SkillCatalog, SkillLoadError
from mini_code_agent.skills.models import SkillId, SkillIssueCode
from mini_code_agent.tools.base import SideEffect, ToolDefinition


class _ListSkillsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LoadSkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: SkillId
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


_LOAD_MESSAGES = {
    SkillIssueCode.UNKNOWN_SKILL: "The requested Skill was not discovered.",
    SkillIssueCode.SKILL_DISABLED: "The requested Skill is disabled.",
    SkillIssueCode.NOT_MODEL_INVOCABLE: "The requested Skill is not available to the model.",
    SkillIssueCode.SKILL_CHANGED: "The requested Skill changed and must be rediscovered.",
    SkillIssueCode.SKILL_UNAVAILABLE: "The requested Skill is unavailable.",
}


class ListSkillsTool:
    _definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="list_skills",
        description="List bounded metadata for model-invocable Skills.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        side_effect=SideEffect.READ_ONLY,
    )

    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != self._definition.name:
            return _error(call.id, "unknown_tool", "The requested tool is not list_skills.")
        try:
            _ListSkillsArguments.model_validate(call.model_dump(mode="json")["arguments"])
        except ValidationError:
            return _error(call.id, "invalid_arguments", "list_skills arguments are invalid.")
        payload = {
            "issues": [
                issue.model_dump(mode="json", exclude_none=True)
                for issue in self._catalog.report.issues
            ],
            "skills": [
                descriptor.model_dump(mode="json") for descriptor in self._catalog.model_descriptors
            ],
        }
        return _result(call.id, payload)


class LoadSkillTool:
    _definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="load_skill",
        description="Load one unchanged model-invocable Skill as untrusted Markdown.",
        input_schema={
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "pattern": (
                        r"^(managed|user|project):"
                        r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
                    ),
                    "minLength": 3,
                    "maxLength": 72,
                },
                "expected_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
            "required": ["skill_id", "expected_sha256"],
            "additionalProperties": False,
        },
        side_effect=SideEffect.READ_ONLY,
    )

    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != self._definition.name:
            return _error(call.id, "unknown_tool", "The requested tool is not load_skill.")
        try:
            arguments = _LoadSkillArguments.model_validate(
                call.model_dump(mode="json")["arguments"]
            )
        except ValidationError:
            return _error(call.id, "invalid_arguments", "load_skill arguments are invalid.")
        try:
            loaded = await asyncio.to_thread(
                self._catalog.load,
                arguments.skill_id,
                expected_sha256=arguments.expected_sha256,
            )
        except SkillLoadError as exc:
            return _error(
                call.id,
                exc.code.value,
                _LOAD_MESSAGES.get(exc.code, "The requested Skill is unavailable."),
            )
        descriptor = loaded.descriptor
        return _result(
            call.id,
            {
                "content": loaded.content,
                "content_type": loaded.content_type,
                "description": descriptor.description,
                "name": descriptor.name,
                "sha256": descriptor.sha256,
                "skill_id": descriptor.skill_id,
                "source": descriptor.source,
                "trust": descriptor.trust,
                "version": descriptor.version,
            },
        )


def _result(call_id: str, payload: object) -> ToolResult:
    return ToolResult(
        tool_call_id=call_id,
        content=json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def _error(call_id: str, code: str, message: str) -> ToolResult:
    return ToolResult(
        tool_call_id=call_id,
        content=json.dumps(
            {"error": {"code": code, "message": message}},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        is_error=True,
    )

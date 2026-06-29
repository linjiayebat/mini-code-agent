from __future__ import annotations

import json

from mini_code_agent.domain.content import ToolResult
from mini_code_agent.workspace.models import MutationResult


def mutation_result(call_id: str, result: MutationResult) -> ToolResult:
    return ToolResult(
        tool_call_id=call_id,
        content=json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def mutation_error(call_id: str, code: str, message: str) -> ToolResult:
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

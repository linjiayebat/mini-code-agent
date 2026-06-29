from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mini_code_agent.domain.content import ToolCall
from mini_code_agent.policy.models import RiskLevel
from mini_code_agent.tools.base import SideEffect
from mini_code_agent.tools.edit_file import EditFileTool
from mini_code_agent.tools.registry import ToolRegistry
from mini_code_agent.workspace.boundary import WorkspaceBoundary


def edit_call(
    expected_sha256: str,
    *,
    old_text: str = "old",
    new_text: str = "new",
) -> ToolCall:
    return ToolCall(
        id="edit-1",
        name="edit_file",
        arguments={
            "path": "app.py",
            "old_text": old_text,
            "new_text": new_text,
            "expected_sha256": expected_sha256,
            "reason": "Apply a targeted implementation change.",
        },
    )


def payload(content: str) -> dict[str, object]:
    return json.loads(content)  # type: ignore[no-any-return]


def test_edit_file_definition_requires_snapshot_hash(tmp_path: Path) -> None:
    tool = EditFileTool(WorkspaceBoundary(tmp_path))
    schema = tool.definition.model_dump(mode="json")["input_schema"]

    assert tool.definition.side_effect is SideEffect.WRITE
    assert schema["required"] == [
        "path",
        "old_text",
        "new_text",
        "expected_sha256",
        "reason",
    ]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_edit_file_preview_and_unique_replacement(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("before old after\n", encoding="utf-8")
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    tool = EditFileTool(WorkspaceBoundary(tmp_path))

    preview = await tool.preview(edit_call(before_hash))
    result = await tool.execute(edit_call(before_hash))

    assert preview.risk is RiskLevel.HIGH
    assert preview.resources == ("app.py",)
    assert preview.reason == "Apply a targeted implementation change."
    assert "-before old after" in (preview.diff or "")
    assert "+before new after" in (preview.diff or "")
    assert result.is_error is False
    assert source.read_text(encoding="utf-8") == "before new after\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "old_text", "new_text", "code"),
    [
        ("before\n", "missing", "new", "match_not_found"),
        ("old old\n", "old", "new", "match_not_unique"),
        ("old\n", "old", "old", "no_change"),
    ],
)
async def test_edit_file_requires_one_effective_match(
    tmp_path: Path,
    text: str,
    old_text: str,
    new_text: str,
    code: str,
) -> None:
    source = tmp_path / "app.py"
    source.write_text(text, encoding="utf-8")
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    registry = ToolRegistry([EditFileTool(WorkspaceBoundary(tmp_path))])

    result = await registry.execute(edit_call(before_hash, old_text=old_text, new_text=new_text))

    assert result.is_error is True
    assert payload(result.content)["error"]["code"] == code  # type: ignore[index]
    assert source.read_text(encoding="utf-8") == text


@pytest.mark.asyncio
async def test_edit_file_rejects_stale_snapshot_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("old\n", encoding="utf-8")
    registry = ToolRegistry([EditFileTool(WorkspaceBoundary(tmp_path))])

    result = await registry.execute(edit_call("0" * 64))

    assert payload(result.content)["error"]["code"] == "conflict"  # type: ignore[index]
    assert source.read_text(encoding="utf-8") == "old\n"

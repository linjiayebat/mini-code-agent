from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mini_code_agent.domain.content import ToolCall
from mini_code_agent.policy.models import RiskLevel
from mini_code_agent.tools.base import SideEffect
from mini_code_agent.tools.registry import ToolRegistry
from mini_code_agent.tools.write_file import WriteFileTool
from mini_code_agent.workspace.boundary import WorkspaceBoundary


def write_call(
    *,
    path: str = "src/app.py",
    content: str = "print('new')\n",
    expected_sha256: str | None = None,
) -> ToolCall:
    arguments: dict[str, str] = {
        "path": path,
        "content": content,
        "reason": "Implement the requested behavior.",
    }
    if expected_sha256 is not None:
        arguments["expected_sha256"] = expected_sha256
    return ToolCall(id="write-1", name="write_file", arguments=arguments)


def payload(content: str) -> dict[str, object]:
    return json.loads(content)  # type: ignore[no-any-return]


def test_write_file_definition_is_write_and_closed_schema(tmp_path: Path) -> None:
    tool = WriteFileTool(WorkspaceBoundary(tmp_path))

    schema = tool.definition.model_dump(mode="json")["input_schema"]

    assert tool.definition.name == "write_file"
    assert tool.definition.side_effect is SideEffect.WRITE
    assert schema["required"] == ["path", "content", "reason"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_write_file_preview_exposes_bounded_diff_and_reason(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('old')\n", encoding="utf-8")
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    tool = WriteFileTool(WorkspaceBoundary(tmp_path))

    preview = await tool.preview(write_call(expected_sha256=before_hash))

    assert preview.risk is RiskLevel.HIGH
    assert preview.resources == ("src/app.py",)
    assert preview.reason == "Implement the requested behavior."
    assert "-print('old')" in (preview.diff or "")
    assert "+print('new')" in (preview.diff or "")
    assert source.read_text(encoding="utf-8") == "print('old')\n"


@pytest.mark.asyncio
async def test_write_file_creates_and_replaces_atomically(tmp_path: Path) -> None:
    tool = WriteFileTool(WorkspaceBoundary(tmp_path))
    registry = ToolRegistry([tool])

    created = await registry.execute(write_call(path="new.txt", content="first\n"))
    before_hash = hashlib.sha256(b"first\n").hexdigest()
    replaced = await registry.execute(
        write_call(path="new.txt", content="second\n", expected_sha256=before_hash)
    )

    assert created.is_error is False
    assert payload(created.content)["created"] is True
    assert replaced.is_error is False
    assert payload(replaced.content)["before_sha256"] == before_hash
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "second\n"


@pytest.mark.asyncio
async def test_write_file_rejects_stale_or_missing_hash_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "existing.txt"
    source.write_text("current\n", encoding="utf-8")
    registry = ToolRegistry([WriteFileTool(WorkspaceBoundary(tmp_path))])

    missing = await registry.execute(write_call(path="existing.txt", content="changed\n"))
    stale = await registry.execute(
        write_call(path="existing.txt", content="changed\n", expected_sha256="0" * 64)
    )

    assert payload(missing.content)["error"]["code"] == "conflict"  # type: ignore[index]
    assert payload(stale.content)["error"]["code"] == "conflict"  # type: ignore[index]
    assert source.read_text(encoding="utf-8") == "current\n"


@pytest.mark.asyncio
async def test_write_file_direct_execution_validates_arguments(tmp_path: Path) -> None:
    tool = WriteFileTool(WorkspaceBoundary(tmp_path))
    invalid = ToolCall(
        id="write-1",
        name="write_file",
        arguments={"path": "file.txt", "content": "value\n"},
    )

    result = await tool.execute(invalid)

    assert result.is_error is True
    assert payload(result.content)["error"]["code"] == "invalid_arguments"  # type: ignore[index]
    assert not (tmp_path / "file.txt").exists()

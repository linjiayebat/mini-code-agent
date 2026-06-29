from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mini_code_agent.agent.models import StopReason
from mini_code_agent.agent.runtime import AgentRuntime
from mini_code_agent.domain.content import ToolCall
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.policy.approval import StaticApprovalHandler
from mini_code_agent.policy.engine import PolicyEngine
from mini_code_agent.policy.executor import GovernedToolExecutor
from mini_code_agent.policy.models import SessionMode, TrustSource
from mini_code_agent.providers.base import FinishReason, ModelResponse
from mini_code_agent.providers.fake import ScriptedProvider
from mini_code_agent.tools.edit_file import EditFileTool
from mini_code_agent.tools.read_file import ReadFileTool
from mini_code_agent.tools.registry import ToolRegistry
from mini_code_agent.tools.write_file import WriteFileTool
from mini_code_agent.workspace.boundary import WorkspaceBoundary


def governed_executor(
    root: Path,
    *,
    approved: bool,
    session_mode: SessionMode = SessionMode.INTERACTIVE,
) -> tuple[GovernedToolExecutor, StaticApprovalHandler]:
    workspace = WorkspaceBoundary(root)
    approval = StaticApprovalHandler(approved=approved)
    executor = GovernedToolExecutor(
        ToolRegistry(
            [
                ReadFileTool(workspace),
                WriteFileTool(workspace),
                EditFileTool(workspace),
            ]
        ),
        policy=PolicyEngine(),
        approval=approval,
        session_mode=session_mode,
        trust_source=TrustSource.MODEL,
    )
    return executor, approval


@pytest.mark.asyncio
async def test_agent_reads_then_edits_after_explicit_approval(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def value():\n    return 'old'\n", encoding="utf-8")
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    executor, approval = governed_executor(tmp_path, approved=True)
    provider = ScriptedProvider(
        [
            ModelResponse(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolCall(
                            id="read-1",
                            name="read_file",
                            arguments={"path": "app.py"},
                        ),
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALL,
            ),
            ModelResponse(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolCall(
                            id="edit-1",
                            name="edit_file",
                            arguments={
                                "path": "app.py",
                                "old_text": "return 'old'",
                                "new_text": "return 'new'",
                                "expected_sha256": before_hash,
                                "reason": "Update the requested return value.",
                            },
                        ),
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALL,
            ),
            ModelResponse(
                message=Message.assistant_text("Updated app.py."),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )

    result = await AgentRuntime(provider, executor).run(
        user_prompt="Change the return value.",
        run_id="governed-write-run",
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.tool_calls == 2
    assert source.read_text(encoding="utf-8") == "def value():\n    return 'new'\n"
    assert len(approval.requests) == 1
    preview = approval.requests[0].preview
    assert preview.resources == ("app.py",)
    assert preview.reason == "Update the requested return value."
    assert "-    return 'old'" in (preview.diff or "")
    assert "+    return 'new'" in (preview.diff or "")
    read_payload = json.loads(provider.requests[1].messages[-1].tool_results[0].content)
    assert read_payload["sha256"] == before_hash


@pytest.mark.asyncio
async def test_denied_write_does_not_mutate_workspace(tmp_path: Path) -> None:
    executor, approval = governed_executor(tmp_path, approved=False)
    call = ToolCall(
        id="write-1",
        name="write_file",
        arguments={
            "path": "new.txt",
            "content": "value\n",
            "reason": "Create the requested file.",
        },
    )

    result = await executor.execute(call)

    assert result.is_error is True
    assert json.loads(result.content)["error"]["code"] == "permission_denied"
    assert len(approval.requests) == 1
    assert not (tmp_path / "new.txt").exists()


@pytest.mark.asyncio
async def test_non_interactive_write_never_prompts_or_mutates(tmp_path: Path) -> None:
    executor, approval = governed_executor(
        tmp_path,
        approved=True,
        session_mode=SessionMode.NON_INTERACTIVE,
    )
    call = ToolCall(
        id="write-1",
        name="write_file",
        arguments={
            "path": "new.txt",
            "content": "value\n",
            "reason": "Create the requested file.",
        },
    )

    result = await executor.execute(call)

    assert result.is_error is True
    assert json.loads(result.content)["error"]["code"] == "permission_denied"
    assert approval.requests == []
    assert not (tmp_path / "new.txt").exists()

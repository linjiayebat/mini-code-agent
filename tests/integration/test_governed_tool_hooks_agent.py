import json
from pathlib import Path

import pytest

from mini_code_agent.agent.models import StopReason
from mini_code_agent.agent.runtime import AgentRuntime
from mini_code_agent.domain.content import ToolCall
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.hooks import (
    HookDecision,
    HookPhase,
    HookRegistration,
    HookSource,
    PostToolHookContext,
    PreToolHookResult,
    RecordingHookAuditSink,
    ToolHookContext,
    ToolHookRunner,
)
from mini_code_agent.policy.approval import StaticApprovalHandler
from mini_code_agent.policy.engine import PolicyEngine
from mini_code_agent.policy.executor import GovernedToolExecutor
from mini_code_agent.policy.models import SessionMode, TrustSource
from mini_code_agent.providers.base import FinishReason, ModelResponse
from mini_code_agent.providers.fake import ScriptedProvider
from mini_code_agent.tools.read_file import ReadFileTool
from mini_code_agent.tools.registry import ToolRegistry
from mini_code_agent.tools.write_file import WriteFileTool
from mini_code_agent.workspace.boundary import WorkspaceBoundary


class BlockWritesHook:
    async def before_tool(self, context: ToolHookContext) -> PreToolHookResult:
        del context
        return PreToolHookResult(
            decision=HookDecision.BLOCK,
            public_reason="Writes are blocked by the host.",
        )


class FailingObserver:
    async def after_tool(self, context: PostToolHookContext) -> None:
        del context
        raise RuntimeError("observer-secret")


class RecordingObserver:
    def __init__(self) -> None:
        self.contexts: list[PostToolHookContext] = []

    async def after_tool(self, context: PostToolHookContext) -> None:
        self.contexts.append(context)


def response_for(call: ToolCall) -> ModelResponse:
    return ModelResponse(
        message=Message(role=MessageRole.ASSISTANT, content=(call,)),
        finish_reason=FinishReason.TOOL_CALL,
    )


@pytest.mark.asyncio
async def test_pre_hook_blocks_real_agent_write_before_mutation(tmp_path: Path) -> None:
    audit = RecordingHookAuditSink()
    hooks = ToolHookRunner(
        (
            HookRegistration(
                hook_id="block-writes",
                source=HookSource.MANAGED,
                priority=0,
                phase=HookPhase.PRE_TOOL,
                handler=BlockWritesHook(),
            ),
        ),
        audit=audit,
    )
    executor = GovernedToolExecutor(
        ToolRegistry([WriteFileTool(WorkspaceBoundary(tmp_path))]),
        policy=PolicyEngine(),
        approval=StaticApprovalHandler(approved=True),
        session_mode=SessionMode.INTERACTIVE,
        trust_source=TrustSource.MODEL,
        hooks=hooks,
    )
    provider = ScriptedProvider(
        (
            response_for(
                ToolCall(
                    id="write-1",
                    name="write_file",
                    arguments={
                        "path": "blocked.txt",
                        "content": "must not exist\n",
                        "reason": "Exercise the pre-Hook.",
                    },
                )
            ),
            ModelResponse(
                message=Message.assistant_text("The host blocked the write."),
                finish_reason=FinishReason.STOP,
            ),
        )
    )

    result = await AgentRuntime(provider, executor).run(
        user_prompt="Create blocked.txt.",
        run_id="hook-block-run",
    )

    assert result.stop_reason is StopReason.COMPLETED
    denied = provider.requests[1].messages[-1].tool_results[0]
    assert json.loads(denied.content)["error"]["code"] == "permission_denied"
    assert not (tmp_path / "blocked.txt").exists()
    assert [record.outcome.value for record in audit.records] == ["blocked"]


@pytest.mark.asyncio
async def test_post_hook_failure_does_not_replace_read_result_or_later_observer(
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.py"
    source.write_bytes(b"VALUE = 42\n")
    observer = RecordingObserver()
    hooks = ToolHookRunner(
        (
            HookRegistration(
                hook_id="a-failing-observer",
                source=HookSource.MANAGED,
                priority=0,
                phase=HookPhase.POST_TOOL,
                handler=FailingObserver(),
            ),
            HookRegistration(
                hook_id="b-recording-observer",
                source=HookSource.MANAGED,
                priority=0,
                phase=HookPhase.POST_TOOL,
                handler=observer,
            ),
        )
    )
    executor = GovernedToolExecutor(
        ToolRegistry([ReadFileTool(WorkspaceBoundary(tmp_path))]),
        policy=PolicyEngine(),
        approval=StaticApprovalHandler(approved=False),
        session_mode=SessionMode.INTERACTIVE,
        trust_source=TrustSource.MODEL,
        hooks=hooks,
    )
    provider = ScriptedProvider(
        (
            response_for(
                ToolCall(
                    id="read-1",
                    name="read_file",
                    arguments={"path": "app.py"},
                )
            ),
            ModelResponse(
                message=Message.assistant_text("Read completed."),
                finish_reason=FinishReason.STOP,
            ),
        )
    )

    result = await AgentRuntime(provider, executor).run(
        user_prompt="Read app.py.",
        run_id="hook-observe-run",
    )

    assert result.stop_reason is StopReason.COMPLETED
    tool_result = provider.requests[1].messages[-1].tool_results[0]
    assert json.loads(tool_result.content)["content"] == "VALUE = 42\n"
    assert len(observer.contexts) == 1
    assert observer.contexts[0].result.content == tool_result.content

from __future__ import annotations

from typing import ClassVar

import pytest

from mini_code_agent.agent.events import ContextCompacted, RecordingEventSink
from mini_code_agent.agent.models import StopReason
from mini_code_agent.agent.runtime import AgentRuntime
from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.providers.base import FinishReason, ModelResponse
from mini_code_agent.providers.fake import ScriptedProvider
from mini_code_agent.tools.base import SideEffect, ToolDefinition


class LargeResultTool:
    _definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="large_result",
        description="Return bounded deterministic test content.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        side_effect=SideEffect.READ_ONLY,
    )

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (self._definition,)

    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            content=f"{call.id}:" + "x" * 16_000,
        )


def tool_response(call_id: str) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role=MessageRole.ASSISTANT,
            content=(
                ToolCall(
                    id=call_id,
                    name="large_result",
                    arguments={},
                ),
            ),
        ),
        finish_reason=FinishReason.TOOL_CALL,
    )


@pytest.mark.asyncio
async def test_default_context_manager_compacts_large_completed_exchanges() -> None:
    provider = ScriptedProvider(
        [
            tool_response("large-1"),
            tool_response("large-2"),
            ModelResponse(
                message=Message.assistant_text("done"),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    events = RecordingEventSink()
    runtime = AgentRuntime(provider, LargeResultTool(), events=events)

    result = await runtime.run(
        user_prompt="Inspect two large results.",
        run_id="large-context-run",
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert len(provider.requests[1].messages) == 3
    assert len(provider.requests[2].messages) == 3
    assert provider.requests[2].messages[0] == result.messages[0]
    assert provider.requests[2].messages[1:3] == result.messages[3:5]
    assert len(result.messages) == 6
    compacted = [event for event in events.events if isinstance(event, ContextCompacted)]
    assert len(compacted) == 1
    assert compacted[0].turn == 3
    assert compacted[0].omitted_messages == 2
    assert compacted[0].omitted_tool_exchanges == 1


@pytest.mark.asyncio
async def test_oversized_original_goal_stops_before_provider_io() -> None:
    provider = ScriptedProvider(
        [
            ModelResponse(
                message=Message.assistant_text("must not run"),
                finish_reason=FinishReason.STOP,
            )
        ]
    )
    runtime = AgentRuntime(provider, LargeResultTool())

    result = await runtime.run(
        user_prompt="secret-large-goal-" + "x" * 30_000,
        run_id="oversized-goal-run",
    )

    assert result.stop_reason is StopReason.CONTEXT_LIMIT
    assert result.turns == 0
    assert provider.requests == []
    assert result.error == "Model context limit exceeded."
    assert "secret-large-goal" not in (result.error or "")

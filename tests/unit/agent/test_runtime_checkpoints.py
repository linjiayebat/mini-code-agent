from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mini_code_agent.agent.events import AgentEvent, RunStarted
from mini_code_agent.agent.models import AgentLimits, StopReason
from mini_code_agent.agent.runtime import AgentRuntime
from mini_code_agent.checkpoint.models import (
    CheckpointDraft,
    CheckpointSnapshot,
    CheckpointStatus,
    ResumeState,
)
from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.providers.base import FinishReason, ModelResponse
from mini_code_agent.providers.fake import ScriptedProvider
from mini_code_agent.tools.runtime_info import RuntimeInfoTool


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def append(self, event: AgentEvent) -> None:
        self.events.append(event)


class StaticWorkspace:
    def current_sha256(self) -> str:
        return "b" * 64


class RecordingCheckpoints:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.drafts: list[CheckpointDraft] = []
        self._fail_at = fail_at

    def save(self, draft: CheckpointDraft) -> CheckpointSnapshot:
        self.drafts.append(draft)
        if self._fail_at == len(self.drafts):
            raise RuntimeError("secret save failure")
        payload = draft.model_dump()
        return CheckpointSnapshot(
            **payload,
            session_id="session-1",
            trace_sequence=len(self.drafts) + 1,
            trace_head_sha256="c" * 64,
            payload_sha256="d" * 64,
        )


def final_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message.assistant_text(text),
        finish_reason=FinishReason.STOP,
    )


def tool_response() -> ModelResponse:
    return ModelResponse(
        message=Message(
            role=MessageRole.ASSISTANT,
            content=(ToolCall(id="call-1", name="runtime_info", arguments={}),),
        ),
        finish_reason=FinishReason.TOOL_CALL,
    )


def runtime(
    provider: ScriptedProvider,
    checkpoints: RecordingCheckpoints,
    *,
    limits: AgentLimits | None = None,
) -> tuple[AgentRuntime, RecordingJournal]:
    journal = RecordingJournal()
    return (
        AgentRuntime(
            provider,
            RuntimeInfoTool(),
            limits=limits,
            journal=journal,
            checkpoints=checkpoints,
            workspace=StaticWorkspace(),
        ),
        journal,
    )


@pytest.mark.asyncio
async def test_runtime_saves_initial_and_post_tool_stable_checkpoints() -> None:
    checkpoints = RecordingCheckpoints()
    agent, _ = runtime(
        ScriptedProvider([tool_response(), final_response("done")]),
        checkpoints,
    )

    result = await agent.run(
        user_prompt="inspect",
        system_prompt="be precise",
        run_id="run-1",
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert len(checkpoints.drafts) == 2
    assert checkpoints.drafts[0].turns == 0
    assert len(checkpoints.drafts[0].messages) == 1
    assert checkpoints.drafts[1].turns == 1
    assert len(checkpoints.drafts[1].messages) == 3
    assert checkpoints.drafts[1].seen_call_ids == frozenset({"call-1"})


@pytest.mark.asyncio
async def test_initial_checkpoint_failure_prevents_provider_io() -> None:
    provider = ScriptedProvider([final_response("must not run")])
    checkpoints = RecordingCheckpoints(fail_at=1)
    agent, journal = runtime(provider, checkpoints)

    result = await agent.run(user_prompt="inspect", run_id="run-1")

    assert result.stop_reason is StopReason.PERSISTENCE_ERROR
    assert provider.requests == []
    assert len(journal.events) == 1
    assert isinstance(journal.events[0], RunStarted)


@pytest.mark.asyncio
async def test_post_tool_checkpoint_failure_prevents_next_provider_io() -> None:
    provider = ScriptedProvider([tool_response(), final_response("must not run")])
    checkpoints = RecordingCheckpoints(fail_at=2)
    agent, _ = runtime(provider, checkpoints)

    result = await agent.run(user_prompt="inspect", run_id="run-1")

    assert result.stop_reason is StopReason.PERSISTENCE_ERROR
    assert len(provider.requests) == 1
    assert result.tool_calls == 1


def consumed_state(*, turns: int = 1) -> ResumeState:
    now = datetime.now(UTC)
    checkpoint = CheckpointSnapshot(
        checkpoint_id="checkpoint-1",
        session_id="session-1",
        source_run_id="run-1",
        trace_sequence=2,
        trace_head_sha256="a" * 64,
        created_at=now,
        system_prompt="be precise",
        messages=(
            Message.user_text("inspect"),
            Message(
                role=MessageRole.ASSISTANT,
                content=(ToolCall(id="call-1", name="runtime_info", arguments={}),),
            ),
            Message(
                role=MessageRole.USER,
                content=(ToolResult(tool_call_id="call-1", content="ok"),),
            ),
        ),
        turns=turns,
        tool_calls=1,
        seen_call_ids=frozenset({"call-1"}),
        tool_contract_sha256="a" * 64,
        workspace_sha256="b" * 64,
        payload_sha256="c" * 64,
        status=CheckpointStatus.CONSUMED,
        resumed_run_id="run-2",
        consumed_at=now,
    )
    return ResumeState(checkpoint=checkpoint, resumed_run_id="run-2")


@pytest.mark.asyncio
async def test_resume_continues_next_turn_without_duplicate_run_started() -> None:
    provider = ScriptedProvider([final_response("done")])
    checkpoints = RecordingCheckpoints()
    agent, journal = runtime(provider, checkpoints)

    result = await agent.resume(consumed_state())

    assert result.stop_reason is StopReason.COMPLETED
    assert provider.requests[0].request_id == "run-2:2"
    assert not any(isinstance(event, RunStarted) for event in journal.events)
    assert checkpoints.drafts[0].source_run_id == "run-2"

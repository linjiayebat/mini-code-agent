from __future__ import annotations

import asyncio
import json

import pytest

from mini_code_agent.agent.events import RunStarted
from mini_code_agent.agent.models import AgentResult, StopReason
from mini_code_agent.policy.models import (
    ActionPreview,
    ApprovalRequest,
    RiskLevel,
)
from mini_code_agent.providers.base import TokenUsage
from mini_code_agent.tools.base import SideEffect
from mini_code_agent.web.manager import (
    RunConflictError,
    WebRunManager,
    WebRunStatus,
)


def completed_result(*, final_text: str = "done") -> AgentResult:
    return AgentResult(
        run_id="agent-run",
        messages=(),
        stop_reason=StopReason.COMPLETED,
        turns=1,
        tool_calls=0,
        usage=TokenUsage(input_tokens=4, output_tokens=2),
        final_text=final_text,
    )


@pytest.mark.asyncio
async def test_manager_publishes_monotonic_redacted_lifecycle() -> None:
    secret_prompt = "inspect project with sk-live-secret"

    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del approval
        assert prompt == secret_prompt
        events.publish(RunStarted(run_id="agent-run", max_turns=8))  # type: ignore[attr-defined]
        return completed_result()

    manager = WebRunManager(runner)
    snapshot = await manager.start(secret_prompt)
    terminal = await manager.wait(snapshot.run_id)
    recorded = manager.events_after(snapshot.run_id)

    assert terminal.status is WebRunStatus.COMPLETED
    assert [event.sequence for event in recorded] == list(range(1, len(recorded) + 1))
    assert [event.type for event in recorded] == [
        "web_run_started",
        "agent_event",
        "web_run_completed",
    ]
    serialized = json.dumps(
        [event.model_dump(mode="json") for event in recorded],
        ensure_ascii=False,
    )
    assert secret_prompt not in serialized
    assert "sk-live-secret" not in serialized
    assert recorded[-1].payload["final_text"] == "done"


@pytest.mark.asyncio
async def test_manager_allows_only_one_active_run() -> None:
    release = asyncio.Event()

    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, approval, events
        await release.wait()
        return completed_result()

    manager = WebRunManager(runner)
    first = await manager.start("first")

    with pytest.raises(RunConflictError):
        await manager.start("second")

    release.set()
    await manager.wait(first.run_id)
    second = await manager.start("second")
    release.set()
    await manager.wait(second.run_id)


@pytest.mark.asyncio
async def test_manager_retains_latest_run_detail_outside_event_payloads() -> None:
    secret_prompt = "Explain the project without exposing this prompt in events."

    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del approval, events
        assert prompt == secret_prompt
        return completed_result(final_text="Explanation")

    manager = WebRunManager(runner)
    started = await manager.start(secret_prompt)
    await manager.wait(started.run_id)

    latest = manager.latest_snapshot()
    detail = manager.detail(started.run_id)
    serialized_events = json.dumps(
        [event.model_dump(mode="json") for event in manager.events_after(started.run_id)]
    )

    assert latest is not None
    assert latest.run_id == started.run_id
    assert detail.prompt == secret_prompt
    assert detail.status is WebRunStatus.COMPLETED
    assert detail.final_text == "Explanation"
    assert secret_prompt not in serialized_events


@pytest.mark.asyncio
async def test_manager_retains_a_bounded_ordered_run_history() -> None:
    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del approval, events
        return completed_result(final_text=f"answer:{prompt}")

    manager = WebRunManager(runner, max_retained_runs=2)
    for prompt in ("first", "second", "third"):
        started = await manager.start(prompt)
        await manager.wait(started.run_id)

    details = manager.details()

    assert [detail.prompt for detail in details] == ["second", "third"]
    assert [detail.final_text for detail in details] == [
        "answer:second",
        "answer:third",
    ]


@pytest.mark.asyncio
async def test_approval_is_bounded_single_use_and_can_be_approved() -> None:
    request = ApprovalRequest(
        preview=ActionPreview(
            tool_call_id="call-1",
            tool_name="run_command",
            side_effect=SideEffect.EXECUTE,
            risk=RiskLevel.HIGH,
            summary="Run focused tests",
            reason="Verify the implementation",
            resources=("tests/unit/web/test_manager.py",),
            command=("python", "-m", "pytest"),
            diff="+ added\n- removed",
        ),
        rule_id="cli-ask-execute",
        rationale="Commands require explicit approval.",
    )
    approval_started = asyncio.Event()

    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, events
        approval_started.set()
        approved = await approval.approve(request)  # type: ignore[attr-defined]
        return completed_result(final_text=f"approved={approved}")

    manager = WebRunManager(runner)
    snapshot = await manager.start("test")
    await approval_started.wait()
    await asyncio.sleep(0)

    approval_event = manager.events_after(snapshot.run_id)[-1]
    assert approval_event.type == "approval_required"
    assert approval_event.payload["preview"]["tool_call_id"] == "call-1"
    assert len(approval_event.payload["preview"]["diff"]) <= 32_768
    assert await manager.decide_approval(snapshot.run_id, "missing", True) is False
    assert await manager.decide_approval(snapshot.run_id, "call-1", True) is True
    assert await manager.decide_approval(snapshot.run_id, "call-1", False) is False

    terminal = await manager.wait(snapshot.run_id)
    assert terminal.status is WebRunStatus.COMPLETED
    assert manager.events_after(snapshot.run_id)[-1].payload["final_text"] == ("approved=True")


@pytest.mark.asyncio
async def test_cancel_rejects_pending_approval_and_emits_one_terminal_event() -> None:
    approval_waiting = asyncio.Event()

    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, events
        approval_waiting.set()
        await approval.approve(  # type: ignore[attr-defined]
            ApprovalRequest(
                preview=ActionPreview(
                    tool_call_id="call-cancel",
                    tool_name="write_file",
                    side_effect=SideEffect.WRITE,
                    risk=RiskLevel.MEDIUM,
                    summary="Write a file",
                ),
                rule_id="write-ask",
                rationale="Writes require approval.",
            )
        )
        return completed_result()

    manager = WebRunManager(runner)
    snapshot = await manager.start("cancel me")
    await approval_waiting.wait()
    await asyncio.sleep(0)

    assert await manager.cancel(snapshot.run_id) is True
    terminal = await manager.wait(snapshot.run_id)
    events = manager.events_after(snapshot.run_id)

    assert terminal.status is WebRunStatus.CANCELLED
    assert [event.type for event in events].count("web_run_cancelled") == 1
    assert await manager.decide_approval(snapshot.run_id, "call-cancel", approved=True) is False

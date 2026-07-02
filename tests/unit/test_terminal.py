from __future__ import annotations

import os
import shlex
import subprocess

import pytest
from rich.console import Console

from mini_code_agent.agent.events import ModelStarted, RunStarted, RunStopped, ToolStarted
from mini_code_agent.agent.models import StopReason
from mini_code_agent.policy.models import (
    ActionPreview,
    ApprovalRequest,
    RiskLevel,
)
from mini_code_agent.providers.base import TokenUsage
from mini_code_agent.terminal import TerminalApprovalHandler, TerminalEventSink
from mini_code_agent.tools.base import SideEffect


def recording_console() -> Console:
    return Console(record=True, width=100, color_system=None)


@pytest.mark.asyncio
async def test_approval_handler_renders_action_details_and_returns_decision() -> None:
    console = recording_console()
    prompts: list[str] = []

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    handler = TerminalApprovalHandler(console=console, confirm=confirm)
    request = ApprovalRequest(
        preview=ActionPreview(
            tool_call_id="edit-1",
            tool_name="edit_file",
            side_effect=SideEffect.WRITE,
            risk=RiskLevel.MEDIUM,
            summary="Edit one workspace file.",
            reason="Implement [red]the requested[/red] behavior.",
            resources=("src/app.py",),
            command=("python", "script with spaces.py", "--name=a b"),
            diff="--- a/src/app.py\n+++ b/src/app.py\n-old\n+new\n",
        ),
        rule_id="default-write",
        rationale="Write tools require approval by default.",
    )

    approved = await handler.approve(request)
    output = console.export_text()

    assert approved is True
    assert prompts == ["Approve this action?"]
    assert "edit_file" in output
    assert "medium" in output
    assert "Implement [red]the requested[/red] behavior." in output
    assert "src/app.py" in output
    command = request.preview.command
    assert command is not None
    expected_command = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    assert expected_command in output
    assert "-old" in output
    assert "+new" in output


@pytest.mark.asyncio
async def test_approval_handler_can_deny_action() -> None:
    handler = TerminalApprovalHandler(
        console=recording_console(),
        confirm=lambda prompt: False,
    )
    request = ApprovalRequest(
        preview=ActionPreview(
            tool_call_id="write-1",
            tool_name="write_file",
            side_effect=SideEffect.WRITE,
            risk=RiskLevel.MEDIUM,
            summary="Create one workspace file.",
        ),
        rule_id="default-write",
        rationale="Write tools require approval by default.",
    )

    assert await handler.approve(request) is False


def test_event_sink_renders_bounded_lifecycle_metadata_only() -> None:
    console = recording_console()
    sink = TerminalEventSink(console=console)

    sink.publish(RunStarted(run_id="run-1", max_turns=8))
    sink.publish(ModelStarted(run_id="run-1", turn=1, request_id="request-1"))
    sink.publish(
        ToolStarted(
            run_id="run-1",
            turn=1,
            tool_call_id="call-1",
            tool_name="read_file",
            side_effect=SideEffect.READ_ONLY,
        )
    )
    sink.publish(
        RunStopped(
            run_id="run-1",
            turns=1,
            reason=StopReason.COMPLETED,
            tool_calls=1,
            usage=TokenUsage(input_tokens=10, output_tokens=4),
        )
    )
    output = console.export_text()

    assert "Run started" in output
    assert "Model turn 1" in output
    assert "read_file" in output
    assert "completed" in output
    assert "input=10" in output
    assert "secret prompt" not in output

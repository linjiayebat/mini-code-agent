from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from mini_code_agent.agent.events import (
    AgentEvent,
    ModelStarted,
    RunStarted,
    RunStopped,
    ToolStarted,
)
from mini_code_agent.policy.models import ApprovalRequest


class TerminalApprovalHandler:
    def __init__(
        self,
        *,
        console: Console,
        confirm: Callable[[str], bool],
    ) -> None:
        self._console = console
        self._confirm = confirm

    async def approve(self, request: ApprovalRequest) -> bool:
        preview = request.preview
        table = Table(title="Approval required", show_header=False)
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Tool", Text(preview.tool_name))
        table.add_row("Risk", Text(preview.risk.value))
        table.add_row("Action", Text(preview.summary))
        table.add_row("Reason", Text(preview.reason))
        if preview.resources:
            table.add_row("Resources", Text("\n".join(preview.resources)))
        if preview.command:
            table.add_row("Command", Text(_format_argv(preview.command)))
        table.add_row("Policy", Text(request.rationale))
        self._console.print(table)
        if preview.diff:
            self._console.print(Syntax(preview.diff, "diff", word_wrap=True))
        return self._confirm("Approve this action?")


class TerminalEventSink:
    def __init__(self, *, console: Console) -> None:
        self._console = console

    def publish(self, event: AgentEvent) -> None:
        if isinstance(event, RunStarted):
            self._console.print(f"[dim]Run started ({event.run_id})[/dim]")
        elif isinstance(event, ModelStarted):
            self._console.print(f"[dim]Model turn {event.turn}[/dim]")
        elif isinstance(event, ToolStarted):
            self._console.print(f"[dim]Tool: {event.tool_name}[/dim]")
        elif isinstance(event, RunStopped):
            self._console.print(
                "[dim]"
                f"Run {event.reason.value}; turns={event.turns}; "
                f"tools={event.tool_calls}; "
                f"tokens input={event.usage.input_tokens} output={event.usage.output_tokens}"
                "[/dim]"
            )


def _format_argv(argv: tuple[str, ...]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)

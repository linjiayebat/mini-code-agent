from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from mini_code_agent import __version__
from mini_code_agent.agent.models import AgentResult
from mini_code_agent.application import (
    DEFAULT_SYSTEM_PROMPT,
    ApplicationConfigurationError,
    run_task,
)
from mini_code_agent.config import (
    AppSettings,
    ConfigurationError,
    default_config_path,
    load_settings,
)
from mini_code_agent.diagnostics import DiagnosticReport, build_diagnostic_report
from mini_code_agent.logging import configure_logging
from mini_code_agent.policy.models import SessionMode
from mini_code_agent.terminal import TerminalApprovalHandler, TerminalEventSink

app = typer.Typer(
    name="mini-code-agent",
    help="Framework-light, provider-neutral coding agent.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
error_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the package version and exit.",
        ),
    ] = False,
) -> None:
    del version


def _render_report(report: DiagnosticReport) -> None:
    table = Table(title="Mini CodeAgent Doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Version", report.package_version)
    table.add_row("Python", report.python_version)
    table.add_row("Python supported", str(report.python_supported))
    table.add_row("Platform", report.platform)
    table.add_row("Config", report.config_path)
    table.add_row("Data directory exists", str(report.data_dir_exists))
    table.add_row("Data directory is directory", str(report.data_dir_is_directory))
    table.add_row("Data path usable", str(report.data_dir_usable))
    table.add_row("Overall healthy", str(report.healthy))
    console.print(table)


def _load_command_settings(config: Path | None) -> AppSettings:
    try:
        settings = load_settings(config_path=config or default_config_path())
    except ConfigurationError as exc:
        error_console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    configured_secrets = (
        secret
        for secret in (settings.anthropic_api_key, settings.openai_api_key)
        if secret is not None
    )
    configure_logging(settings.log_level.value, secrets=configured_secrets)
    return settings


def _render_agent_result(result: AgentResult) -> None:
    if result.final_text:
        console.print(Text(result.final_text))
    console.print(
        "[dim]"
        f"Result: {result.stop_reason.value}; turns={result.turns}; "
        f"tools={result.tool_calls}; "
        f"tokens input={result.usage.input_tokens} output={result.usage.output_tokens}"
        "[/dim]"
    )
    if result.error:
        error_console.print(f"[red]Agent stopped:[/red] {result.error}")


def _execute_task(
    settings: AppSettings,
    *,
    workspace: Path,
    user_prompt: str,
    system_prompt: str,
    session_mode: SessionMode,
) -> AgentResult:
    approval = TerminalApprovalHandler(
        console=console,
        confirm=lambda prompt: typer.confirm(prompt, default=False),
    )
    try:
        return asyncio.run(
            run_task(
                settings,
                workspace=workspace,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                approval=approval,
                session_mode=session_mode,
                events=TerminalEventSink(console=console),
            )
        )
    except ApplicationConfigurationError as exc:
        error_console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


@app.command()
def doctor(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to a TOML configuration file."),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit a machine-readable JSON report."),
    ] = False,
) -> None:
    config_path = config or default_config_path()
    try:
        settings = load_settings(config_path=config_path)
    except ConfigurationError as exc:
        if output_json:
            typer.echo(json.dumps({"error": str(exc)}, ensure_ascii=False), err=True)
        else:
            error_console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configured_secrets = (
        secret
        for secret in (settings.anthropic_api_key, settings.openai_api_key)
        if secret is not None
    )
    configure_logging(settings.log_level.value, secrets=configured_secrets)
    report = build_diagnostic_report(settings, config_path=config_path)
    if output_json:
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_report(report)
    if not report.healthy:
        raise typer.Exit(code=1)


@app.command("run")
def run_agent_command(
    task: Annotated[str, typer.Argument(help="Task for the coding agent.")],
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace directory. Defaults to the current one."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to a TOML configuration file."),
    ] = None,
    system_prompt: Annotated[
        str | None,
        typer.Option("--system-prompt", help="Override the built-in coding-agent instructions."),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Deny writes and commands instead of prompting.",
        ),
    ] = False,
) -> None:
    settings = _load_command_settings(config)
    mode = SessionMode.NON_INTERACTIVE if non_interactive else SessionMode.INTERACTIVE
    result = _execute_task(
        settings,
        workspace=workspace or Path.cwd(),
        user_prompt=task,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        session_mode=mode,
    )
    _render_agent_result(result)
    if not result.succeeded:
        raise typer.Exit(code=1)


@app.command()
def chat(
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace directory. Defaults to the current one."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to a TOML configuration file."),
    ] = None,
    system_prompt: Annotated[
        str | None,
        typer.Option("--system-prompt", help="Override the built-in coding-agent instructions."),
    ] = None,
) -> None:
    settings = _load_command_settings(config)
    active_workspace = workspace or Path.cwd()
    active_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    console.print(
        "[dim]Interactive task mode. Each prompt starts an independent bounded run. "
        "Use /exit or /quit to stop.[/dim]"
    )
    failed = False
    while True:
        try:
            task = typer.prompt("task")
        except (EOFError, typer.Abort):
            break
        if task.strip().lower() in {"/exit", "/quit"}:
            break
        if not task.strip():
            continue
        result = _execute_task(
            settings,
            workspace=active_workspace,
            user_prompt=task,
            system_prompt=active_system_prompt,
            session_mode=SessionMode.INTERACTIVE,
        )
        _render_agent_result(result)
        failed = failed or not result.succeeded
    if failed:
        raise typer.Exit(code=1)

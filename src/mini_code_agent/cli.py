from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mini_code_agent import __version__
from mini_code_agent.config import (
    ConfigurationError,
    default_config_path,
    load_settings,
)
from mini_code_agent.diagnostics import DiagnosticReport, build_diagnostic_report
from mini_code_agent.logging import configure_logging

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
    table.add_row("Data directory writable", str(report.data_dir_parent_writable))
    console.print(table)


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

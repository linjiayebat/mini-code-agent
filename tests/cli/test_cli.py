import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mini_code_agent.agent.models import AgentResult, StopReason
from mini_code_agent.application import ApplicationConfigurationError
from mini_code_agent.cli import app
from mini_code_agent.policy.models import SessionMode
from mini_code_agent.providers.base import TokenUsage

runner = CliRunner()


@pytest.fixture(autouse=True)
def clear_project_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MINI_CODE_AGENT_LOG_LEVEL",
        "MINI_CODE_AGENT_DATA_DIR",
        "MINI_CODE_AGENT_TRACE_ENABLED",
        "MINI_CODE_AGENT_ANTHROPIC_API_KEY",
        "MINI_CODE_AGENT_OPENAI_API_KEY",
        "MINI_CODE_AGENT_PROVIDER",
        "MINI_CODE_AGENT_MODEL",
        "MINI_CODE_AGENT_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def agent_result(
    *,
    reason: StopReason = StopReason.COMPLETED,
    final_text: str | None = "Inspected the project.",
    error: str | None = None,
) -> AgentResult:
    return AgentResult(
        run_id="run-1",
        messages=(),
        stop_reason=reason,
        turns=1,
        tool_calls=0,
        usage=TokenUsage(input_tokens=10, output_tokens=4),
        final_text=final_text,
        error=error,
    )


def test_version_option_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.18.0a0"


def test_module_entrypoint_prints_package_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mini_code_agent", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "0.18.0a0"


def test_doctor_json_never_prints_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINI_CODE_AGENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MINI_CODE_AGENT_ANTHROPIC_API_KEY", "must-not-appear")

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["settings"]["anthropic_api_key_configured"] is True
    assert "must-not-appear" not in result.stdout


def test_doctor_returns_configuration_exit_code_two(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("mini_code_agent = 7", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--config", str(config_path), "--json"])

    assert result.exit_code == 2
    assert "must be a TOML table" in result.stderr


def test_doctor_invalid_environment_returns_json_exit_code_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINI_CODE_AGENT_LOG_LEVEL", "definitely-invalid")

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.stderr)
    assert "Invalid application configuration" in payload["error"]
    assert "Traceback" not in result.stderr


def test_doctor_validation_error_never_prints_secret(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid-secret.toml"
    config_path.write_text(
        """
[mini_code_agent]
anthropic_api_key = { value = "validation-secret" }
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["doctor", "--config", str(config_path), "--json"])

    assert result.exit_code == 2
    assert "validation-secret" not in result.stderr


def test_doctor_human_output_explains_unusable_data_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_file = tmp_path / "data-file"
    data_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("MINI_CODE_AGENT_DATA_DIR", str(data_file))

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "Data path usable" in result.stdout
    assert "Overall healthy" in result.stdout
    assert "False" in result.stdout


def test_run_executes_one_task_and_renders_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_run_task(*args: object, **kwargs: object) -> AgentResult:
        calls.append(dict(kwargs))
        return agent_result()

    monkeypatch.setattr("mini_code_agent.cli.run_task", fake_run_task)
    monkeypatch.setenv("MINI_CODE_AGENT_MODEL", "Pro/zai-org/GLM-4.7")
    monkeypatch.setenv("MINI_CODE_AGENT_OPENAI_API_KEY", "test-key")

    result = runner.invoke(
        app,
        ["run", "Inspect this project.", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Inspected the project." in result.stdout
    assert "completed" in result.stdout
    assert calls[0]["workspace"] == tmp_path
    assert calls[0]["user_prompt"] == "Inspect this project."
    assert calls[0]["session_mode"] is SessionMode.INTERACTIVE


def test_run_non_interactive_forwards_policy_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modes: list[SessionMode] = []

    async def fake_run_task(*args: object, **kwargs: object) -> AgentResult:
        modes.append(kwargs["session_mode"])  # type: ignore[arg-type]
        return agent_result()

    monkeypatch.setattr("mini_code_agent.cli.run_task", fake_run_task)
    monkeypatch.setenv("MINI_CODE_AGENT_MODEL", "model-1")
    monkeypatch.setenv("MINI_CODE_AGENT_OPENAI_API_KEY", "test-key")

    result = runner.invoke(
        app,
        [
            "run",
            "Inspect.",
            "--workspace",
            str(tmp_path),
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0
    assert modes == [SessionMode.NON_INTERACTIVE]


def test_run_configuration_error_exits_two_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_task(*args: object, **kwargs: object) -> AgentResult:
        raise ApplicationConfigurationError("Set MINI_CODE_AGENT_MODEL.")

    monkeypatch.setattr("mini_code_agent.cli.run_task", fake_run_task)

    result = runner.invoke(
        app,
        ["run", "Inspect.", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "Set MINI_CODE_AGENT_MODEL" in result.stderr
    assert "Traceback" not in result.stderr


def test_run_agent_failure_exits_one_and_renders_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_task(*args: object, **kwargs: object) -> AgentResult:
        return agent_result(
            reason=StopReason.PROVIDER_ERROR,
            final_text=None,
            error="Provider authentication failed.",
        )

    monkeypatch.setattr("mini_code_agent.cli.run_task", fake_run_task)

    result = runner.invoke(
        app,
        ["run", "Inspect.", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Provider authentication failed." in result.stderr
    assert "Traceback" not in result.stderr


def test_chat_runs_each_prompt_until_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    async def fake_run_task(*args: object, **kwargs: object) -> AgentResult:
        prompts.append(str(kwargs["user_prompt"]))
        return agent_result(final_text=f"Completed: {kwargs['user_prompt']}")

    monkeypatch.setattr("mini_code_agent.cli.run_task", fake_run_task)
    monkeypatch.setenv("MINI_CODE_AGENT_MODEL", "model-1")
    monkeypatch.setenv("MINI_CODE_AGENT_OPENAI_API_KEY", "test-key")

    result = runner.invoke(
        app,
        ["chat", "--workspace", str(tmp_path)],
        input="Inspect files.\nSummarize changes.\n/exit\n",
    )

    assert result.exit_code == 0
    assert prompts == ["Inspect files.", "Summarize changes."]
    assert "Completed: Inspect files." in result.stdout
    assert "Completed: Summarize changes." in result.stdout
    assert "independent bounded run" in result.stdout


def test_web_starts_loopback_server_and_opens_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = object()
    created: list[dict[str, object]] = []
    served: list[dict[str, object]] = []
    opened: list[str] = []

    def fake_create_web_app(*args: object, **kwargs: object) -> object:
        created.append(dict(kwargs))
        return fake_app

    def fake_uvicorn_run(app_object: object, **kwargs: object) -> None:
        assert app_object is fake_app
        served.append(dict(kwargs))

    monkeypatch.setattr("mini_code_agent.cli.create_web_app", fake_create_web_app)
    monkeypatch.setattr("mini_code_agent.cli.uvicorn.run", fake_uvicorn_run)

    def fake_open(url: str) -> None:
        opened.append(url)

    monkeypatch.setattr("mini_code_agent.cli._schedule_browser_open", fake_open)
    monkeypatch.setenv("MINI_CODE_AGENT_MODEL", "Pro/zai-org/GLM-4.7")
    monkeypatch.setenv("MINI_CODE_AGENT_OPENAI_API_KEY", "test-key")

    result = runner.invoke(
        app,
        [
            "web",
            "--workspace",
            str(tmp_path),
            "--port",
            "9876",
        ],
    )

    assert result.exit_code == 0
    assert created[0]["workspace"] == tmp_path
    assert served == [
        {
            "host": "127.0.0.1",
            "port": 9876,
            "log_level": "info",
        }
    ]
    assert opened == ["http://127.0.0.1:9876"]


def test_web_no_open_skips_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_web_app(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return object()

    def fake_uvicorn_run(*args: object, **kwargs: object) -> None:
        del args, kwargs

    def fail_open(url: str) -> None:
        pytest.fail(f"unexpected browser open: {url}")

    monkeypatch.setattr("mini_code_agent.cli.create_web_app", fake_create_web_app)
    monkeypatch.setattr("mini_code_agent.cli.uvicorn.run", fake_uvicorn_run)
    monkeypatch.setattr("mini_code_agent.cli._schedule_browser_open", fail_open)

    result = runner.invoke(
        app,
        ["web", "--workspace", str(tmp_path), "--no-open"],
    )

    assert result.exit_code == 0


def test_web_rejects_non_loopback_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_uvicorn(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("server must not start")

    monkeypatch.setattr("mini_code_agent.cli.uvicorn.run", fail_uvicorn)

    result = runner.invoke(
        app,
        ["web", "--workspace", str(tmp_path), "--host", "0.0.0.0"],
    )

    assert result.exit_code == 2
    assert "loopback" in result.stderr.lower()

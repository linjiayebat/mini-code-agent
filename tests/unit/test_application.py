from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mini_code_agent.agent.events import RecordingEventSink
from mini_code_agent.agent.models import StopReason
from mini_code_agent.application import (
    ApplicationConfigurationError,
    build_provider,
    build_tool_executor,
    run_task,
)
from mini_code_agent.config import AppSettings, ProviderName
from mini_code_agent.domain.content import ToolCall
from mini_code_agent.domain.messages import Message
from mini_code_agent.policy.approval import StaticApprovalHandler
from mini_code_agent.policy.models import SessionMode
from mini_code_agent.providers.base import FinishReason, ModelRequest, ModelResponse
from mini_code_agent.providers.fake import ScriptedProvider


def settings_for(tmp_path: Path, **overrides: object) -> AppSettings:
    return AppSettings.model_validate(
        {
            "data_dir": tmp_path / "data",
            "provider": "openai_compatible",
            "model": "Pro/zai-org/GLM-4.7",
            "base_url": "https://api.siliconflow.cn/v1",
            "openai_api_key": "test-key",
            **overrides,
        }
    )


def test_build_provider_requires_model_before_network_access(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, model=None)

    with pytest.raises(ApplicationConfigurationError, match="model"):
        build_provider(settings)


@pytest.mark.parametrize(
    ("provider", "settings_values", "message"),
    [
        (
            ProviderName.OPENAI_COMPATIBLE,
            {"openai_api_key": None},
            "MINI_CODE_AGENT_OPENAI_API_KEY",
        ),
        (
            ProviderName.ANTHROPIC,
            {
                "provider": "anthropic",
                "openai_api_key": None,
                "anthropic_api_key": None,
            },
            "MINI_CODE_AGENT_ANTHROPIC_API_KEY",
        ),
    ],
)
def test_build_provider_requires_matching_api_key(
    tmp_path: Path,
    provider: ProviderName,
    settings_values: dict[str, object],
    message: str,
) -> None:
    settings = settings_for(tmp_path, **settings_values)
    assert settings.provider is provider

    with pytest.raises(ApplicationConfigurationError, match=message):
        build_provider(settings)


@pytest.mark.asyncio
async def test_openai_compatible_provider_uses_siliconflow_endpoint(tmp_path: Path) -> None:
    captured_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = build_provider(settings_for(tmp_path), client=client)
    try:
        response = await provider.complete(
            ModelRequest(
                request_id="siliconflow-smoke",
                system_prompt="",
                messages=(Message.user_text("hello"),),
            )
        )
    finally:
        await provider.aclose()
        await client.aclose()

    assert response.message.text == "ok"
    assert captured_urls == ["https://api.siliconflow.cn/v1/chat/completions"]


@pytest.mark.asyncio
async def test_tool_executor_registers_cli_tools_and_asks_for_commands(tmp_path: Path) -> None:
    approval = StaticApprovalHandler(approved=False)
    executor = build_tool_executor(
        tmp_path,
        approval=approval,
        session_mode=SessionMode.INTERACTIVE,
    )

    names = tuple(definition.name for definition in executor.definitions)
    result = await executor.execute(
        ToolCall(
            id="command-1",
            name="run_command",
            arguments={
                "argv": ["python", "--version"],
                "reason": "Check the Python version.",
            },
        )
    )

    assert names == (
        "read_file",
        "search_text",
        "write_file",
        "edit_file",
        "git_status",
        "git_diff",
        "run_command",
    )
    assert json.loads(result.content)["error"]["code"] == "permission_denied"
    assert len(approval.requests) == 1
    assert approval.requests[0].preview.command == ("python", "--version")


class ClosableScriptedProvider(ScriptedProvider):
    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__(responses)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_task_executes_runtime_and_closes_provider(tmp_path: Path) -> None:
    provider = ClosableScriptedProvider(
        [
            ModelResponse(
                message=Message.assistant_text("Inspected the project."),
                finish_reason=FinishReason.STOP,
            )
        ]
    )
    events = RecordingEventSink()

    result = await run_task(
        settings_for(tmp_path),
        workspace=tmp_path,
        user_prompt="Inspect this project.",
        approval=StaticApprovalHandler(approved=False),
        session_mode=SessionMode.INTERACTIVE,
        events=events,
        provider_factory=lambda settings: provider,
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.final_text == "Inspected the project."
    assert provider.closed is True
    assert [event.type for event in events.events] == [
        "run_started",
        "model_started",
        "model_completed",
        "run_stopped",
    ]


@pytest.mark.asyncio
async def test_run_task_closes_provider_when_runtime_fails(tmp_path: Path) -> None:
    provider = ClosableScriptedProvider([])

    result = await run_task(
        settings_for(tmp_path),
        workspace=tmp_path,
        user_prompt="Inspect this project.",
        approval=StaticApprovalHandler(approved=False),
        session_mode=SessionMode.NON_INTERACTIVE,
        provider_factory=lambda settings: provider,
    )

    assert result.stop_reason is StopReason.PROVIDER_ERROR
    assert provider.closed is True


@pytest.mark.asyncio
async def test_build_provider_selects_anthropic(tmp_path: Path) -> None:
    settings = settings_for(
        tmp_path,
        provider="anthropic",
        model="claude-sonnet-4-5",
        base_url=None,
        openai_api_key=None,
        anthropic_api_key=SecretStr("anthropic-key"),
    )

    provider = build_provider(settings)
    try:
        assert provider.__class__.__name__ == "AnthropicProvider"
    finally:
        await provider.aclose()

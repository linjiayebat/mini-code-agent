from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from mini_code_agent.domain.content import TextBlock, ToolCall, ToolResult
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.providers.anthropic import AnthropicProvider
from mini_code_agent.providers.base import (
    FinishReason,
    ModelRequest,
    ProviderError,
    ProviderErrorCode,
    TokenUsage,
)
from mini_code_agent.tools.base import SideEffect, ToolDefinition


def runtime_tool() -> ToolDefinition:
    return ToolDefinition(
        name="runtime_info",
        description="Return runtime metadata.",
        input_schema={
            "type": "object",
            "properties": {"verbose": {"type": "boolean"}},
        },
        side_effect=SideEffect.READ_ONLY,
    )


def tool_round_trip_request() -> ModelRequest:
    return ModelRequest(
        request_id="local-request-1",
        system_prompt="Work carefully.",
        messages=(
            Message.user_text("Inspect."),
            Message(
                role=MessageRole.ASSISTANT,
                content=(
                    ToolCall(
                        id="call-1",
                        name="runtime_info",
                        arguments={},
                    ),
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=(
                    TextBlock(text="Continue after the result."),
                    ToolResult(
                        tool_call_id="call-1",
                        content="{}",
                    ),
                ),
            ),
        ),
        tools=(runtime_tool(),),
    )


def anthropic_response(
    *,
    content: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": content if content is not None else [{"type": "text", "text": "done"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 12, "output_tokens": 7},
    }


def provider_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[AnthropicProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider(
        api_key=SecretStr("test-key"),
        model="claude-test",
        max_tokens=1024,
        base_url="https://provider.test",
        client=client,
    )
    return provider, client


@pytest.mark.asyncio
async def test_complete_converts_domain_request_to_anthropic_messages() -> None:
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == "https://provider.test/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["content-type"] == "application/json"
        captured_body.update(cast(dict[str, Any], json.loads(request.content)))
        return httpx.Response(
            200,
            json=anthropic_response(),
            headers={"request-id": "req_1"},
            request=request,
        )

    provider, client = provider_with_handler(handler)

    result = await provider.complete(tool_round_trip_request())

    assert captured_body == {
        "model": "claude-test",
        "max_tokens": 1024,
        "system": "Work carefully.",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Inspect."}],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "runtime_info",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": "{}",
                        "is_error": False,
                    },
                    {
                        "type": "text",
                        "text": "Continue after the result.",
                    },
                ],
            },
        ],
        "tools": [
            {
                "name": "runtime_info",
                "description": "Return runtime metadata.",
                "input_schema": {
                    "type": "object",
                    "properties": {"verbose": {"type": "boolean"}},
                },
            }
        ],
    }
    assert result.message.text == "done"
    assert result.finish_reason is FinishReason.STOP
    assert result.usage == TokenUsage(input_tokens=12, output_tokens=7)
    assert result.provider_request_id == "req_1"
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_omits_empty_system_and_tools() -> None:
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(cast(dict[str, Any], json.loads(request.content)))
        return httpx.Response(200, json=anthropic_response(), request=request)

    provider, client = provider_with_handler(handler)
    request = ModelRequest(
        request_id="request-1",
        system_prompt="",
        messages=(Message.user_text("hello"),),
    )

    await provider.complete(request)

    assert "system" not in captured_body
    assert "tools" not in captured_body
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_normalizes_text_and_parallel_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=anthropic_response(
                content=[
                    {"type": "text", "text": "Checking."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "runtime_info",
                        "input": {"verbose": True},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "runtime_info",
                        "input": {"verbose": False},
                    },
                ],
                stop_reason="tool_use",
                usage={
                    "input_tokens": 12,
                    "output_tokens": 7,
                    "cache_read_input_tokens": 4,
                },
            ),
            request=request,
        )

    provider, client = provider_with_handler(handler)

    result = await provider.complete(
        ModelRequest(
            request_id="request-1",
            system_prompt="",
            messages=(Message.user_text("inspect"),),
            tools=(runtime_tool(),),
        )
    )

    assert result.finish_reason is FinishReason.TOOL_CALL
    assert result.message.text == "Checking."
    assert result.message.tool_calls == (
        ToolCall(
            id="toolu_1",
            name="runtime_info",
            arguments={"verbose": True},
        ),
        ToolCall(
            id="toolu_2",
            name="runtime_info",
            arguments={"verbose": False},
        ),
    )
    assert provider.capabilities.parallel_tool_calls is True
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", FinishReason.STOP),
        ("stop_sequence", FinishReason.STOP),
        ("max_tokens", FinishReason.MAX_TOKENS),
        ("model_context_window_exceeded", FinishReason.MAX_TOKENS),
        ("refusal", FinishReason.CONTENT_FILTER),
    ],
)
async def test_complete_maps_supported_stop_reasons(
    stop_reason: str,
    expected: FinishReason,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=anthropic_response(stop_reason=stop_reason),
            request=request,
        )

    provider, client = provider_with_handler(handler)
    request = ModelRequest(
        request_id="request-1",
        system_prompt="",
        messages=(Message.user_text("hello"),),
    )

    result = await provider.complete(request)

    assert result.finish_reason is expected
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_body",
    [
        anthropic_response(content=[], stop_reason="end_turn"),
        anthropic_response(
            content=[{"type": "thinking", "thinking": "hidden"}],
            stop_reason="end_turn",
        ),
        anthropic_response(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "runtime_info",
                    "input": [],
                }
            ],
            stop_reason="tool_use",
        ),
        anthropic_response(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "runtime_info",
                    "input": {},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "runtime_info",
                    "input": {},
                },
            ],
            stop_reason="tool_use",
        ),
        anthropic_response(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "runtime_info",
                    "input": {},
                }
            ],
            stop_reason="end_turn",
        ),
        anthropic_response(stop_reason="pause_turn"),
        {**anthropic_response(), "role": "user"},
        {**anthropic_response(), "usage": {"input_tokens": -1, "output_tokens": 2}},
    ],
)
async def test_complete_rejects_malformed_or_lossy_response(
    response_body: dict[str, Any],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_body, request=request)

    provider, client = provider_with_handler(handler)
    request = ModelRequest(
        request_id="request-1",
        system_prompt="",
        messages=(Message.user_text("hello"),),
    )

    with pytest.raises(ProviderError) as captured:
        await provider.complete(request)

    assert captured.value.code is ProviderErrorCode.INVALID_RESPONSE
    assert captured.value.retryable is False
    await client.aclose()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"model": "x" * 257},
        {"model": "bad model"},
        {"max_tokens": 0},
        {"max_tokens": 1_000_001},
        {"anthropic_version": "latest"},
    ],
)
def test_provider_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    arguments: dict[str, object] = {
        "api_key": SecretStr("test-key"),
        "model": "claude-test",
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError):
        AnthropicProvider(**arguments)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_provider_close_does_not_close_borrowed_client() -> None:
    provider, client = provider_with_handler(
        lambda request: httpx.Response(200, json=anthropic_response(), request=request)
    )

    await provider.aclose()

    assert client.is_closed is False
    await client.aclose()

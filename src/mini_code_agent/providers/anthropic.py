from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Annotated, Final, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    ValidationError,
)

from mini_code_agent.domain.content import TextBlock, ToolCall, ToolResult
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.providers.base import (
    FinishReason,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorCode,
    ProviderStreamEvent,
    TokenUsage,
)
from mini_code_agent.providers.http import ProviderHttpTransport

_MODEL_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_VERSION_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CAPABILITIES: Final = ProviderCapabilities(parallel_tool_calls=True)


class _AnthropicTextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str = Field(min_length=1)


class _AnthropicToolUseBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_use"]
    id: str = Field(min_length=1, max_length=128)
    name: str
    input: dict[str, JsonValue]


type _AnthropicContentBlock = Annotated[
    _AnthropicTextBlock | _AnthropicToolUseBlock,
    Field(discriminator="type"),
]


class _AnthropicUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class _AnthropicMessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=256)
    type: Literal["message"]
    role: Literal["assistant"]
    content: tuple[_AnthropicContentBlock, ...] = Field(min_length=1)
    stop_reason: Literal[
        "end_turn",
        "max_tokens",
        "stop_sequence",
        "tool_use",
        "pause_turn",
        "refusal",
        "model_context_window_exceeded",
    ]
    usage: _AnthropicUsage


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        max_tokens: int = 4096,
        base_url: str = "https://api.anthropic.com",
        anthropic_version: str = "2023-06-01",
        timeout_seconds: float = 60.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        key = api_key.get_secret_value()
        if not key or len(key) > 4_096 or "\r" in key or "\n" in key:
            raise ValueError("api_key must contain between 1 and 4096 safe characters")
        if not _MODEL_PATTERN.fullmatch(model):
            raise ValueError("model must be a valid provider model identifier")
        if not 1 <= max_tokens <= 1_000_000:
            raise ValueError("max_tokens must be between 1 and 1000000")
        if not _VERSION_PATTERN.fullmatch(anthropic_version):
            raise ValueError("anthropic_version must use YYYY-MM-DD format")

        self._api_key = key
        self._model = model
        self._max_tokens = max_tokens
        self._anthropic_version = anthropic_version
        self._transport = ProviderHttpTransport(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            client=client,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _CAPABILITIES

    async def complete(self, request: ModelRequest) -> ModelResponse:
        payload, request_id = await self._transport.post_json(
            "v1/messages",
            headers=self._headers(),
            payload=self._request_payload(request, stream=False),
        )
        return self._parse_response(payload, request_id=request_id)

    async def stream(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        del request
        raise ProviderError(
            ProviderErrorCode.INVALID_RESPONSE,
            "Anthropic streaming is not available.",
            retryable=False,
        )
        yield

    async def aclose(self) -> None:
        await self._transport.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": self._anthropic_version,
            "content-type": "application/json",
        }

    def _request_payload(
        self,
        request: ModelRequest,
        *,
        stream: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [self._message_payload(message) for message in request.messages],
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if request.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.model_dump(mode="json")["input_schema"],
                }
                for tool in request.tools
            ]
        if stream:
            payload["stream"] = True
        return payload

    @staticmethod
    def _message_payload(message: Message) -> dict[str, object]:
        if message.role is MessageRole.USER:
            result_blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_call_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
                for block in message.content
                if isinstance(block, ToolResult)
            ]
            text_blocks = [
                {"type": "text", "text": block.text}
                for block in message.content
                if isinstance(block, TextBlock)
            ]
            return {
                "role": "user",
                "content": [*result_blocks, *text_blocks],
            }

        content: list[dict[str, object]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolCall):
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.model_dump(mode="json")["arguments"],
                    }
                )
        return {"role": "assistant", "content": content}

    @staticmethod
    def _parse_response(
        payload: dict[str, JsonValue],
        *,
        request_id: str | None,
    ) -> ModelResponse:
        try:
            wire = _AnthropicMessageResponse.model_validate(payload)
            if wire.stop_reason == "pause_turn":
                raise ValueError("pause_turn cannot be represented losslessly")

            content: list[TextBlock | ToolCall] = []
            tool_ids: set[str] = set()
            for block in wire.content:
                if isinstance(block, _AnthropicTextBlock):
                    content.append(TextBlock(text=block.text))
                    continue
                if block.id in tool_ids:
                    raise ValueError("duplicate tool call id")
                tool_ids.add(block.id)
                content.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

            finish_reason = _map_finish_reason(wire.stop_reason)
            return ModelResponse(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=tuple(content),
                ),
                finish_reason=finish_reason,
                usage=TokenUsage(
                    input_tokens=wire.usage.input_tokens,
                    output_tokens=wire.usage.output_tokens,
                ),
                provider_request_id=request_id,
            )
        except (ValidationError, ValueError, TypeError):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Anthropic returned an invalid response.",
                retryable=False,
            ) from None


def _map_finish_reason(value: str) -> FinishReason:
    if value in {"end_turn", "stop_sequence"}:
        return FinishReason.STOP
    if value == "tool_use":
        return FinishReason.TOOL_CALL
    if value in {"max_tokens", "model_context_window_exceeded"}:
        return FinishReason.MAX_TOKENS
    if value == "refusal":
        return FinishReason.CONTENT_FILTER
    raise ValueError("unsupported Anthropic stop reason")

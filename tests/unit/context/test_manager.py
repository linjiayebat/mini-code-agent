from __future__ import annotations

import json

import pytest

from mini_code_agent.context.errors import ContextError, ContextErrorCode
from mini_code_agent.context.manager import ContextManager
from mini_code_agent.context.models import ContextLimits
from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.tools.base import ToolDefinition


class FixedUnitEstimator:
    def estimate(
        self,
        *,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> int:
        del tools
        marker_cost = 100 if "[context-omitted " in system_prompt else 0
        return 10 + marker_cost + len(messages) * 100


class FixedCostEstimator:
    def __init__(self, cost: int) -> None:
        self._cost = cost

    def estimate(
        self,
        *,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> int:
        del system_prompt, messages, tools
        return self._cost


class RaisingEstimator:
    def estimate(
        self,
        *,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> int:
        del system_prompt, messages, tools
        raise RuntimeError("secret-estimator-failure")


def exchange(
    call_ids: tuple[str, ...],
    *,
    result_ids: tuple[str, ...] | None = None,
    secret: str = "",
) -> tuple[Message, Message]:
    calls = Message(
        role=MessageRole.ASSISTANT,
        content=tuple(
            ToolCall(
                id=call_id,
                name="test_tool",
                arguments={"value": f"{secret}{call_id}"},
            )
            for call_id in call_ids
        ),
    )
    results = Message(
        role=MessageRole.USER,
        content=tuple(
            ToolResult(
                tool_call_id=result_id,
                content=json.dumps({"result": f"{secret}{result_id}"}),
            )
            for result_id in (result_ids if result_ids is not None else call_ids)
        ),
    )
    return calls, results


def transcript(exchange_count: int, *, secret: str = "") -> tuple[Message, ...]:
    messages: list[Message] = [Message.user_text("original goal")]
    for index in range(exchange_count):
        messages.extend(exchange((f"call-{index}",), secret=secret))
    return tuple(messages)


def manager(*, usable_budget: int) -> ContextManager:
    return ContextManager(
        limits=ContextLimits(
            max_context_tokens=usable_budget + 1,
            reserved_output_tokens=1,
        ),
        estimator=FixedUnitEstimator(),
    )


def test_full_context_is_unchanged_when_it_fits() -> None:
    messages = transcript(2)

    window = manager(usable_budget=510).prepare(
        system_prompt="system",
        messages=messages,
        tools=(),
    )

    assert window.messages == messages
    assert window.system_prompt == "system"
    assert window.estimated_before == 510
    assert window.estimated_after == 510
    assert window.compacted is False
    assert window.omitted_messages == 0
    assert len(window.transcript_sha256) == 64


@pytest.mark.parametrize("budget", [609, 610, 611])
def test_compaction_keeps_a_contiguous_recent_suffix_at_boundaries(
    budget: int,
) -> None:
    messages = transcript(3)

    window = manager(usable_budget=budget).prepare(
        system_prompt="system",
        messages=messages,
        tools=(),
    )

    expected_exchanges = 2 if budget >= 610 else 1
    expected_message_count = 1 + expected_exchanges * 2
    assert window.messages[0] == messages[0]
    assert window.messages[1:] == messages[-(expected_exchanges * 2) :]
    assert len(window.messages) == expected_message_count
    assert window.estimated_after <= budget
    assert window.omitted_messages == len(messages) - expected_message_count
    assert window.omitted_tool_exchanges == 3 - expected_exchanges
    assert window.compacted is True


def test_parallel_tool_batch_is_atomic_and_result_order_may_differ() -> None:
    calls, results = exchange(
        ("call-a", "call-b"),
        result_ids=("call-b", "call-a"),
    )
    messages = (Message.user_text("goal"), calls, results)

    window = manager(usable_budget=500).prepare(
        system_prompt="",
        messages=messages,
        tools=(),
    )

    assert window.messages == messages


@pytest.mark.parametrize(
    "messages",
    [
        (Message.assistant_text("not a user goal"),),
        (
            Message.user_text("goal"),
            Message(
                role=MessageRole.USER,
                content=(ToolResult(tool_call_id="orphan", content="result"),),
            ),
        ),
        (
            Message.user_text("goal"),
            exchange(("call-1",))[0],
        ),
        (
            Message.user_text("goal"),
            *exchange(("call-1",), result_ids=("different",)),
        ),
        (
            Message.user_text("goal"),
            *exchange(("call-1", "call-1")),
        ),
    ],
)
def test_invalid_transcript_fails_without_leaking_content(
    messages: tuple[Message, ...],
) -> None:
    with pytest.raises(ContextError) as captured:
        manager(usable_budget=1_000).prepare(
            system_prompt="",
            messages=messages,
            tools=(),
        )

    assert captured.value.code is ContextErrorCode.INVALID_TRANSCRIPT
    assert "call-1" not in captured.value.public_message
    assert "orphan" not in captured.value.public_message


def test_fixed_content_overflow_is_distinct() -> None:
    context = ContextManager(
        limits=ContextLimits(max_context_tokens=400, reserved_output_tokens=1),
        estimator=FixedCostEstimator(500),
    )

    with pytest.raises(ContextError) as captured:
        context.prepare(
            system_prompt="oversized-system",
            messages=(Message.user_text("goal"),),
            tools=(),
        )

    assert captured.value.code is ContextErrorCode.FIXED_CONTENT_TOO_LARGE


def test_latest_exchange_overflow_is_distinct() -> None:
    context = manager(usable_budget=309)

    with pytest.raises(ContextError) as captured:
        context.prepare(
            system_prompt="",
            messages=transcript(1),
            tools=(),
        )

    assert captured.value.code is ContextErrorCode.LATEST_EXCHANGE_TOO_LARGE


def test_marker_and_error_do_not_include_omitted_content() -> None:
    secret = "secret-omitted-payload"
    messages = (
        Message.user_text("goal"),
        *exchange(("old-secret",), secret=secret),
        *exchange(("recent-1",)),
        *exchange(("recent-2",)),
    )
    window = manager(usable_budget=410).prepare(
        system_prompt="system",
        messages=messages,
        tools=(),
    )

    assert secret not in window.system_prompt
    assert secret not in window.model_dump_json()
    assert "[context-omitted " in window.system_prompt
    assert "do-not-guess" in window.system_prompt
    assert len(window.system_prompt) <= len("system\n\n") + 500


def test_fingerprint_is_stable_and_changes_with_transcript() -> None:
    first = manager(usable_budget=510).prepare(
        system_prompt="",
        messages=transcript(2),
        tools=(),
    )
    repeated = manager(usable_budget=510).prepare(
        system_prompt="",
        messages=transcript(2),
        tools=(),
    )
    changed = manager(usable_budget=510).prepare(
        system_prompt="",
        messages=(Message.user_text("different goal"), *transcript(2)[1:]),
        tools=(),
    )

    assert first.transcript_sha256 == repeated.transcript_sha256
    assert changed.transcript_sha256 != first.transcript_sha256


def test_unexpected_estimator_failure_is_normalized() -> None:
    context = ContextManager(estimator=RaisingEstimator())

    with pytest.raises(ContextError) as captured:
        context.prepare(
            system_prompt="",
            messages=(Message.user_text("secret-content"),),
            tools=(),
        )

    assert captured.value.code is ContextErrorCode.WINDOW_BUILD_FAILED
    assert "secret-estimator-failure" not in captured.value.public_message
    assert "secret-content" not in captured.value.public_message

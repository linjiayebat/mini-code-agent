from __future__ import annotations

import json

import pytest

from mini_code_agent.context.errors import ContextError, ContextErrorCode
from mini_code_agent.context.manager import ContextManager
from mini_code_agent.context.models import ContextLimits
from mini_code_agent.domain.content import ToolCall, ToolResult
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.tools.base import SideEffect, ToolDefinition

READ_TOOL = ToolDefinition(
    name="test_tool",
    description="Read-only test tool.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    side_effect=SideEffect.READ_ONLY,
)
WRITE_TOOL = ToolDefinition(
    name="write_tool",
    description="Write test tool.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    side_effect=SideEffect.WRITE,
)
READ_TOOLS = (READ_TOOL,)


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
    tool_name: str = "test_tool",
) -> tuple[Message, Message]:
    calls = Message(
        role=MessageRole.ASSISTANT,
        content=tuple(
            ToolCall(
                id=call_id,
                name=tool_name,
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
        tools=READ_TOOLS,
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
        tools=READ_TOOLS,
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
        tools=READ_TOOLS,
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
            tools=READ_TOOLS,
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
            tools=READ_TOOLS,
        )

    assert captured.value.code is ContextErrorCode.FIXED_CONTENT_TOO_LARGE


def test_latest_exchange_overflow_is_distinct() -> None:
    context = manager(usable_budget=309)

    with pytest.raises(ContextError) as captured:
        context.prepare(
            system_prompt="",
            messages=transcript(1),
            tools=READ_TOOLS,
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
        tools=READ_TOOLS,
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
        tools=READ_TOOLS,
    )
    repeated = manager(usable_budget=510).prepare(
        system_prompt="",
        messages=transcript(2),
        tools=READ_TOOLS,
    )
    changed = manager(usable_budget=510).prepare(
        system_prompt="",
        messages=(Message.user_text("different goal"), *transcript(2)[1:]),
        tools=READ_TOOLS,
    )

    assert first.transcript_sha256 == repeated.transcript_sha256
    assert changed.transcript_sha256 != first.transcript_sha256


def test_unexpected_estimator_failure_is_normalized() -> None:
    context = ContextManager(estimator=RaisingEstimator())

    with pytest.raises(ContextError) as captured:
        context.prepare(
            system_prompt="",
            messages=(Message.user_text("secret-content"),),
            tools=READ_TOOLS,
        )

    assert captured.value.code is ContextErrorCode.WINDOW_BUILD_FAILED
    assert "secret-estimator-failure" not in captured.value.public_message
    assert "secret-content" not in captured.value.public_message


def test_side_effect_exchange_is_pinned_while_older_read_is_omitted() -> None:
    write_exchange = exchange(("write-1",), tool_name="write_tool")
    old_read = exchange(("read-1",))
    latest_read = exchange(("read-2",))
    messages = (
        Message.user_text("goal"),
        *write_exchange,
        *old_read,
        *latest_read,
    )

    window = manager(usable_budget=610).prepare(
        system_prompt="",
        messages=messages,
        tools=(READ_TOOL, WRITE_TOOL),
    )

    assert window.messages == (
        messages[0],
        *write_exchange,
        *latest_read,
    )
    assert window.omitted_messages == 2
    assert window.omitted_tool_exchanges == 1


def test_unknown_tool_exchange_is_pinned_conservatively() -> None:
    unknown_exchange = exchange(("unknown-1",), tool_name="unknown_tool")
    old_read = exchange(("read-1",))
    latest_read = exchange(("read-2",))
    messages = (
        Message.user_text("goal"),
        *unknown_exchange,
        *old_read,
        *latest_read,
    )

    window = manager(usable_budget=610).prepare(
        system_prompt="",
        messages=messages,
        tools=READ_TOOLS,
    )

    assert window.messages == (
        messages[0],
        *unknown_exchange,
        *latest_read,
    )
    assert window.omitted_messages == 2
    assert window.omitted_tool_exchanges == 1


def test_pinned_side_effect_history_fails_closed_when_it_cannot_fit() -> None:
    messages = (
        Message.user_text("goal"),
        *exchange(("write-1",), tool_name="write_tool"),
        *exchange(("read-1",)),
        *exchange(("read-2",)),
    )

    with pytest.raises(ContextError) as captured:
        manager(usable_budget=609).prepare(
            system_prompt="",
            messages=messages,
            tools=(READ_TOOL, WRITE_TOOL),
        )

    assert captured.value.code is ContextErrorCode.PINNED_HISTORY_TOO_LARGE

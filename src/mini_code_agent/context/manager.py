from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from mini_code_agent.context.errors import ContextError, ContextErrorCode
from mini_code_agent.context.estimator import TokenEstimator, Utf8TokenEstimator
from mini_code_agent.context.models import ContextLimits, ContextWindow
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.tools.base import SideEffect, ToolDefinition


class ContextPreparer(Protocol):
    def prepare(
        self,
        *,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> ContextWindow: ...


@dataclass(frozen=True, slots=True)
class _ContextUnit:
    messages: tuple[Message, ...]
    tool_exchange: bool
    pinned: bool


class ContextManager:
    def __init__(
        self,
        *,
        limits: ContextLimits | None = None,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self._limits = limits or ContextLimits()
        self._estimator = estimator or Utf8TokenEstimator()

    @property
    def limits(self) -> ContextLimits:
        return self._limits

    def prepare(
        self,
        *,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> ContextWindow:
        try:
            return self._prepare(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
            )
        except ContextError:
            raise
        except Exception:
            raise ContextError(
                ContextErrorCode.WINDOW_BUILD_FAILED,
                "Model context window could not be prepared.",
            ) from None

    def _prepare(
        self,
        *,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> ContextWindow:
        goal, units = _group_transcript(messages, tools)
        fingerprint = _transcript_fingerprint(messages)
        estimated_before = self._estimate(system_prompt, messages, tools)
        budget = self._limits.usable_input_tokens
        if estimated_before <= budget:
            return ContextWindow(
                system_prompt=system_prompt,
                messages=messages,
                estimated_before=estimated_before,
                estimated_after=estimated_before,
                transcript_sha256=fingerprint,
            )

        goal_messages = (goal,)
        if self._estimate(system_prompt, goal_messages, tools) > budget:
            raise ContextError(
                ContextErrorCode.FIXED_CONTENT_TOO_LARGE,
                "Fixed model context exceeds the configured limit.",
            )
        if not units:
            raise ContextError(
                ContextErrorCode.FIXED_CONTENT_TOO_LARGE,
                "Fixed model context exceeds the configured limit.",
            )
        retained_start = len(units) - 1
        candidate = self._build_candidate(
            system_prompt=system_prompt,
            goal=goal,
            units=units,
            retained_start=retained_start,
            fingerprint=fingerprint,
            tools=tools,
        )
        if candidate.estimated_after > budget:
            latest_candidate = self._build_latest_candidate(
                system_prompt=system_prompt,
                goal=goal,
                units=units,
                fingerprint=fingerprint,
                tools=tools,
            )
            if latest_candidate.estimated_after <= budget:
                raise ContextError(
                    ContextErrorCode.PINNED_HISTORY_TOO_LARGE,
                    "Required model context history exceeds the configured limit.",
                )
            raise ContextError(
                ContextErrorCode.LATEST_EXCHANGE_TOO_LARGE,
                "Latest model context exchange exceeds the configured limit.",
            )

        while retained_start > 0:
            next_start = retained_start - 1
            next_candidate = self._build_candidate(
                system_prompt=system_prompt,
                goal=goal,
                units=units,
                retained_start=next_start,
                fingerprint=fingerprint,
                tools=tools,
            )
            if next_candidate.estimated_after > budget:
                break
            candidate = next_candidate
            retained_start = next_start

        if candidate.estimated_after > budget:
            raise ContextError(
                ContextErrorCode.WINDOW_BUILD_FAILED,
                "Model context window could not be prepared.",
            )
        return candidate.model_copy(update={"estimated_before": estimated_before})

    def _build_candidate(
        self,
        *,
        system_prompt: str,
        goal: Message,
        units: tuple[_ContextUnit, ...],
        retained_start: int,
        fingerprint: str,
        tools: tuple[ToolDefinition, ...],
    ) -> ContextWindow:
        selected_units = tuple(
            unit for index, unit in enumerate(units) if unit.pinned or index >= retained_start
        )
        omitted = tuple(
            unit for index, unit in enumerate(units) if not unit.pinned and index < retained_start
        )
        return self._assemble_candidate(
            system_prompt=system_prompt,
            goal=goal,
            selected_units=selected_units,
            omitted=omitted,
            fingerprint=fingerprint,
            tools=tools,
        )

    def _build_latest_candidate(
        self,
        *,
        system_prompt: str,
        goal: Message,
        units: tuple[_ContextUnit, ...],
        fingerprint: str,
        tools: tuple[ToolDefinition, ...],
    ) -> ContextWindow:
        return self._assemble_candidate(
            system_prompt=system_prompt,
            goal=goal,
            selected_units=(units[-1],),
            omitted=units[:-1],
            fingerprint=fingerprint,
            tools=tools,
        )

    def _assemble_candidate(
        self,
        *,
        system_prompt: str,
        goal: Message,
        selected_units: tuple[_ContextUnit, ...],
        omitted: tuple[_ContextUnit, ...],
        fingerprint: str,
        tools: tuple[ToolDefinition, ...],
    ) -> ContextWindow:
        omitted_messages = sum(len(unit.messages) for unit in omitted)
        omitted_exchanges = sum(unit.tool_exchange for unit in omitted)
        prepared_system = system_prompt
        if omitted:
            marker = self._marker(
                omitted_messages=omitted_messages,
                omitted_exchanges=omitted_exchanges,
                fingerprint=fingerprint,
            )
            prepared_system = f"{system_prompt}\n\n{marker}" if system_prompt else marker
        selected = (
            goal,
            *(message for unit in selected_units for message in unit.messages),
        )
        estimated_after = self._estimate(prepared_system, selected, tools)
        return ContextWindow(
            system_prompt=prepared_system,
            messages=selected,
            estimated_before=estimated_after,
            estimated_after=estimated_after,
            omitted_messages=omitted_messages,
            omitted_tool_exchanges=omitted_exchanges,
            transcript_sha256=fingerprint,
        )

    def _marker(
        self,
        *,
        omitted_messages: int,
        omitted_exchanges: int,
        fingerprint: str,
    ) -> str:
        marker = (
            f"[context-omitted m={omitted_messages} x={omitted_exchanges} "
            f"h={fingerprint}; unavailable; do-not-guess]"
        )
        if len(marker) > self._limits.marker_max_chars:
            raise ContextError(
                ContextErrorCode.WINDOW_BUILD_FAILED,
                "Model context window could not be prepared.",
            )
        return marker

    def _estimate(
        self,
        system_prompt: str,
        messages: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> int:
        return self._estimator.estimate(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
        )


def _group_transcript(
    messages: tuple[Message, ...],
    tools: tuple[ToolDefinition, ...],
) -> tuple[Message, tuple[_ContextUnit, ...]]:
    if not messages or messages[0].role is not MessageRole.USER or messages[0].tool_results:
        raise _invalid_transcript()
    goal = messages[0]
    units: list[_ContextUnit] = []
    tool_side_effects = {tool.name: tool.side_effect for tool in tools}
    index = 1
    while index < len(messages):
        message = messages[index]
        if message.tool_results:
            raise _invalid_transcript()
        if not message.tool_calls:
            units.append(
                _ContextUnit(
                    messages=(message,),
                    tool_exchange=False,
                    pinned=False,
                )
            )
            index += 1
            continue
        if index + 1 >= len(messages):
            raise _invalid_transcript()
        result_message = messages[index + 1]
        call_ids = tuple(call.id for call in message.tool_calls)
        result_ids = tuple(result.tool_call_id for result in result_message.tool_results)
        if (
            result_message.role is not MessageRole.USER
            or not result_ids
            or len(call_ids) != len(set(call_ids))
            or len(result_ids) != len(set(result_ids))
            or len(call_ids) != len(result_ids)
            or set(call_ids) != set(result_ids)
        ):
            raise _invalid_transcript()
        pinned = any(
            tool_side_effects.get(call.name) is not SideEffect.READ_ONLY
            for call in message.tool_calls
        )
        units.append(
            _ContextUnit(
                messages=(message, result_message),
                tool_exchange=True,
                pinned=pinned,
            )
        )
        index += 2
    return goal, tuple(units)


def _transcript_fingerprint(messages: tuple[Message, ...]) -> str:
    canonical = json.dumps(
        [message.model_dump(mode="json") for message in messages],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _invalid_transcript() -> ContextError:
    return ContextError(
        ContextErrorCode.INVALID_TRANSCRIPT,
        "Model context transcript is invalid.",
    )

import pytest
from pydantic import ValidationError

from mini_code_agent.agent.events import RecordingEventSink, RunStarted
from mini_code_agent.agent.models import AgentLimits, AgentResult, StopReason
from mini_code_agent.domain.messages import Message
from mini_code_agent.providers.base import TokenUsage


def test_recording_sink_preserves_typed_event_order() -> None:
    sink = RecordingEventSink()
    event = RunStarted(run_id="run-1", max_turns=4)

    sink.publish(event)

    assert sink.events == [event]
    assert sink.events[0].run_id == "run-1"


def test_agent_limits_reject_unbounded_zero_turn_configuration() -> None:
    with pytest.raises(ValidationError):
        AgentLimits(max_turns=0)


def test_agent_result_success_depends_on_stop_reason() -> None:
    result = AgentResult(
        run_id="run-1",
        messages=(Message.user_text("work"), Message.assistant_text("done")),
        stop_reason=StopReason.COMPLETED,
        turns=1,
        tool_calls=0,
        usage=TokenUsage(),
        final_text="done",
    )

    assert result.succeeded is True

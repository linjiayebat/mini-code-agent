import pytest
from pydantic import ValidationError

from mini_code_agent.web.models import (
    ApprovalDecisionRequest,
    StartRunRequest,
    WebEvent,
)


def test_start_run_request_rejects_blank_and_oversized_prompts() -> None:
    with pytest.raises(ValidationError):
        StartRunRequest(prompt="")

    with pytest.raises(ValidationError):
        StartRunRequest(prompt="x" * 20_001)


def test_web_models_are_frozen_and_bounded() -> None:
    event = WebEvent(sequence=1, type="web_run_started", payload={"status": "running"})

    with pytest.raises(ValidationError):
        event.sequence = 2

    assert ApprovalDecisionRequest(approved=True).approved is True

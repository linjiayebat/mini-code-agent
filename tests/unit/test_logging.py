import json
from io import StringIO

from pydantic import SecretStr

from mini_code_agent.logging import configure_logging, redact


def test_redact_masks_sensitive_keys_recursively() -> None:
    payload = {
        "api_key": "secret-a",
        "nested": {
            "authorization": "Bearer secret-b",
            "safe": 7,
        },
        "items": [{"token": "secret-c"}],
        "secret_object": SecretStr("secret-d"),
    }

    redacted = redact(payload)
    rendered = str(redacted)

    assert "secret-a" not in rendered
    assert "secret-b" not in rendered
    assert "secret-c" not in rendered
    assert "secret-d" not in rendered
    nested = redacted["nested"]
    assert nested == {"authorization": "***", "safe": 7}


def test_json_log_contains_safe_event_data() -> None:
    stream = StringIO()
    logger = configure_logging("info", stream=stream)

    logger.info(
        "provider request",
        extra={
            "event_data": {
                "provider": "anthropic",
                "api_key": "must-not-appear",
            }
        },
    )

    event = json.loads(stream.getvalue())
    assert event["level"] == "INFO"
    assert event["message"] == "provider request"
    assert event["data"]["provider"] == "anthropic"
    assert event["data"]["api_key"] == "***"
    assert "must-not-appear" not in stream.getvalue()

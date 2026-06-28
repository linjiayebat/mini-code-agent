from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TextIO, cast, overload

from pydantic import SecretStr

LOGGER_NAME = "mini_code_agent"
MASK = "***"
SENSITIVE_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS)


@overload
def redact(value: Mapping[str, object], *, key: str | None = None) -> dict[str, object]: ...


@overload
def redact(value: object, *, key: str | None = None) -> object: ...


def redact(value: object, *, key: str | None = None) -> object:
    if key is not None and _is_sensitive_key(key):
        return MASK
    if isinstance(value, SecretStr):
        return MASK
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(item_key): redact(item_value, key=str(item_key))
            for item_key, item_value in mapping.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        return [redact(item) for item in sequence]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if event_data is not None:
            payload["data"] = redact(event_data)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    level: str,
    *,
    stream: TextIO | None = None,
) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(level.upper())
    logger.propagate = False

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable, Mapping, Sequence
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


def _normalize_secrets(secrets: Iterable[str | SecretStr]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for secret in secrets:
        value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if value:
            normalized.add(value)
    return tuple(sorted(normalized, key=len, reverse=True))


def _scrub_text(value: str, secrets: tuple[str, ...]) -> str:
    scrubbed = value
    for secret in secrets:
        scrubbed = scrubbed.replace(secret, MASK)
    return scrubbed


def _scrub_known_secrets(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return _scrub_text(value, secrets)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            _scrub_text(str(item_key), secrets): _scrub_known_secrets(item_value, secrets)
            for item_key, item_value in mapping.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        return [_scrub_known_secrets(item, secrets) for item in sequence]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _scrub_text(str(value), secrets)


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: Iterable[str | SecretStr] = ()) -> None:
        super().__init__()
        self._secrets = _normalize_secrets(secrets)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _scrub_text(record.getMessage(), self._secrets),
        }
        event_data = getattr(record, "event_data", None)
        if event_data is not None:
            payload["data"] = _scrub_known_secrets(redact(event_data), self._secrets)
        if record.exc_info:
            payload["exception"] = _scrub_text(
                self.formatException(record.exc_info),
                self._secrets,
            )
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    level: str,
    *,
    stream: TextIO | None = None,
    secrets: Iterable[str | SecretStr] = (),
) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(level.upper())
    logger.propagate = False

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter(secrets))
    logger.addHandler(handler)
    return logger

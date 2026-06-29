from __future__ import annotations

from enum import StrEnum


class ContextErrorCode(StrEnum):
    INVALID_TRANSCRIPT = "invalid_transcript"
    FIXED_CONTENT_TOO_LARGE = "fixed_content_too_large"
    LATEST_EXCHANGE_TOO_LARGE = "latest_exchange_too_large"
    PINNED_HISTORY_TOO_LARGE = "pinned_history_too_large"
    WINDOW_BUILD_FAILED = "window_build_failed"


class ContextError(RuntimeError):
    def __init__(self, code: ContextErrorCode, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message

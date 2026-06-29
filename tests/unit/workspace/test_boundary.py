from pathlib import Path

import pytest
from pydantic import ValidationError

from mini_code_agent.workspace.errors import WorkspaceError, WorkspaceErrorCode
from mini_code_agent.workspace.models import SearchLimits, WorkspaceLimits


def test_workspace_error_exposes_only_safe_public_message(tmp_path: Path) -> None:
    secret_path = str(tmp_path / "private" / "secret.txt")
    error = WorkspaceError(
        WorkspaceErrorCode.OUTSIDE_WORKSPACE,
        "Requested path is outside the workspace.",
    )

    assert error.code is WorkspaceErrorCode.OUTSIDE_WORKSPACE
    assert error.public_message == "Requested path is outside the workspace."
    assert secret_path not in str(error)
    assert error.retryable is False


def test_workspace_error_codes_are_stable() -> None:
    assert {code.value for code in WorkspaceErrorCode} == {
        "invalid_path",
        "outside_workspace",
        "link_traversal",
        "not_found",
        "wrong_file_type",
        "too_large",
        "binary_file",
        "invalid_encoding",
        "traversal_budget",
    }


def test_workspace_limits_have_safe_defaults() -> None:
    limits = WorkspaceLimits()

    assert limits.max_file_bytes == 1024 * 1024
    assert limits.max_path_chars == 1024


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_file_bytes": 0},
        {"max_file_bytes": 16 * 1024 * 1024 + 1},
        {"max_path_chars": 0},
        {"max_path_chars": 1025},
    ],
)
def test_workspace_limits_have_hard_upper_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        WorkspaceLimits(**kwargs)


def test_search_limits_have_safe_defaults() -> None:
    limits = SearchLimits()

    assert limits.max_files == 10_000
    assert limits.max_total_bytes == 64 * 1024 * 1024
    assert limits.max_results == 200
    assert limits.max_depth == 32
    assert limits.max_line_chars == 20_000
    assert limits.max_preview_chars == 500


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_files": 0},
        {"max_files": 100_001},
        {"max_total_bytes": 0},
        {"max_total_bytes": 256 * 1024 * 1024 + 1},
        {"max_results": 0},
        {"max_results": 10_001},
        {"max_depth": 0},
        {"max_depth": 65},
        {"max_line_chars": 0},
        {"max_line_chars": 100_001},
        {"max_preview_chars": 0},
        {"max_preview_chars": 2_001},
    ],
)
def test_search_limits_have_hard_upper_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        SearchLimits(**kwargs)

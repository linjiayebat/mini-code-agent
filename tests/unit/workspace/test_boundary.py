from pathlib import Path

import pytest
from pydantic import ValidationError

from mini_code_agent.workspace.boundary import WorkspaceBoundary
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


def test_boundary_requires_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        WorkspaceBoundary(tmp_path / "missing")

    regular_file = tmp_path / "file.txt"
    regular_file.write_text("content", encoding="utf-8")
    with pytest.raises(ValueError):
        WorkspaceBoundary(regular_file)


def test_boundary_resolves_regular_file_inside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    boundary = WorkspaceBoundary(tmp_path)

    resolved = boundary.resolve_file("src/module.py")

    assert resolved == source.resolve(strict=True)
    assert boundary.relative_path(resolved) == "src/module.py"


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "..",
        "../secret",
        "a/../../secret",
        "/etc/passwd",
        "C:/Windows/system.ini",
        "C:relative.txt",
        "//server/share/file",
        r"\\server\share\file",
        r"dir\file",
        "a/%2e%2e/secret",
        "bad\0name",
        "dir//file",
        "dir/./file",
        "x" * 1025,
    ],
)
def test_resolve_rejects_untrusted_path_forms(tmp_path: Path, path: str) -> None:
    boundary = WorkspaceBoundary(tmp_path)

    with pytest.raises(WorkspaceError) as captured:
        boundary.resolve_file(path)

    assert captured.value.code in {
        WorkspaceErrorCode.INVALID_PATH,
        WorkspaceErrorCode.OUTSIDE_WORKSPACE,
    }
    assert str(tmp_path.resolve()) not in str(captured.value)


def test_resolve_reports_missing_without_absolute_path(tmp_path: Path) -> None:
    boundary = WorkspaceBoundary(tmp_path)

    with pytest.raises(WorkspaceError) as captured:
        boundary.resolve_file("src/missing.py")

    assert captured.value.code is WorkspaceErrorCode.NOT_FOUND
    assert str(tmp_path.resolve()) not in str(captured.value)


def test_resolve_rejects_directory_target(tmp_path: Path) -> None:
    directory = tmp_path / "src"
    directory.mkdir()
    boundary = WorkspaceBoundary(tmp_path)

    with pytest.raises(WorkspaceError) as captured:
        boundary.resolve_file("src")

    assert captured.value.code is WorkspaceErrorCode.WRONG_FILE_TYPE


def test_resolve_rejects_symlink_component(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink unavailable in this environment: {exc}")
    boundary = WorkspaceBoundary(tmp_path)

    with pytest.raises(WorkspaceError) as captured:
        boundary.resolve_file("link/file.txt")

    assert captured.value.code is WorkspaceErrorCode.LINK_TRAVERSAL

from pathlib import Path

import pytest

from mini_code_agent.config import AppSettings
from mini_code_agent.diagnostics import (
    build_diagnostic_report,
    is_supported_python,
)


def test_supported_python_range_is_explicit() -> None:
    assert is_supported_python((3, 12)) is True
    assert is_supported_python((3, 13)) is True
    assert is_supported_python((3, 11)) is False
    assert is_supported_python((3, 14)) is False


def test_report_does_not_create_the_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "not-created"
    settings = AppSettings.model_validate({"data_dir": data_dir})

    report = build_diagnostic_report(
        settings,
        config_path=tmp_path / "missing.toml",
        python_version=(3, 13),
    )

    assert report.healthy is True
    assert report.data_dir_exists is False
    assert report.data_dir_parent_writable is True
    assert data_dir.exists() is False


def test_report_is_unhealthy_when_data_directory_is_a_file(tmp_path: Path) -> None:
    data_file = tmp_path / "data-file"
    data_file.write_text("not a directory", encoding="utf-8")
    settings = AppSettings.model_validate({"data_dir": data_file})

    report = build_diagnostic_report(
        settings,
        config_path=tmp_path / "missing.toml",
        python_version=(3, 13),
    )

    assert report.data_dir_exists is True
    assert report.data_dir_is_directory is False
    assert report.data_dir_usable is False
    assert report.healthy is False


def test_report_is_unhealthy_when_existing_file_blocks_parent_path(tmp_path: Path) -> None:
    blocking_file = tmp_path / "blocking-file"
    blocking_file.write_text("not a directory", encoding="utf-8")
    settings = AppSettings.model_validate({"data_dir": blocking_file / "child"})

    report = build_diagnostic_report(
        settings,
        config_path=tmp_path / "missing.toml",
        python_version=(3, 13),
    )

    assert report.data_dir_exists is False
    assert report.data_dir_parent_writable is False
    assert report.data_dir_usable is False
    assert report.healthy is False


def test_report_is_unhealthy_for_broken_data_directory_symlink(tmp_path: Path) -> None:
    broken_link = tmp_path / "broken-link"
    try:
        broken_link.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable in this environment: {exc}")
    settings = AppSettings.model_validate({"data_dir": broken_link})

    report = build_diagnostic_report(
        settings,
        config_path=tmp_path / "missing.toml",
        python_version=(3, 13),
    )

    assert report.data_dir_exists is False
    assert report.data_dir_parent_writable is False
    assert report.data_dir_usable is False
    assert report.healthy is False

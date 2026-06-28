from pathlib import Path

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

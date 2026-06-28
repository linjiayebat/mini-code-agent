from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mini_code_agent import __version__
from mini_code_agent.config import AppSettings


class DiagnosticReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    package_version: str
    python_version: str
    python_supported: bool
    platform: str
    config_path: str
    config_file_exists: bool
    data_dir_exists: bool
    data_dir_parent_writable: bool
    settings: dict[str, object]

    @property
    def healthy(self) -> bool:
        return self.python_supported and self.data_dir_parent_writable


def is_supported_python(version: tuple[int, int]) -> bool:
    return (3, 12) <= version < (3, 14)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def build_diagnostic_report(
    settings: AppSettings,
    *,
    config_path: Path,
    python_version: tuple[int, int] | None = None,
) -> DiagnosticReport:
    runtime_version = python_version or (sys.version_info.major, sys.version_info.minor)
    existing_parent = _nearest_existing_parent(settings.data_dir)
    return DiagnosticReport(
        package_version=__version__,
        python_version=platform.python_version(),
        python_supported=is_supported_python(runtime_version),
        platform=platform.platform(),
        config_path=str(config_path),
        config_file_exists=config_path.exists(),
        data_dir_exists=settings.data_dir.exists(),
        data_dir_parent_writable=os.access(existing_parent, os.W_OK),
        settings=settings.safe_dict(),
    )

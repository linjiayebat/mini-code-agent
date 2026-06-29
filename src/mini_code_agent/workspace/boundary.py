from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Final

from mini_code_agent.workspace.errors import WorkspaceError, WorkspaceErrorCode
from mini_code_agent.workspace.models import WorkspaceLimits

_WINDOWS_DRIVE: Final = re.compile(r"^[A-Za-z]:")


class WorkspaceBoundary:
    def __init__(
        self,
        root: Path,
        *,
        limits: WorkspaceLimits | None = None,
    ) -> None:
        try:
            resolved_root = root.resolve(strict=True)
        except OSError:
            raise ValueError("workspace root must be an existing directory") from None
        if not resolved_root.is_dir():
            raise ValueError("workspace root must be an existing directory")

        self._root = resolved_root
        self._limits = limits or WorkspaceLimits()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def limits(self) -> WorkspaceLimits:
        return self._limits

    def resolve_file(self, untrusted_path: str) -> Path:
        parts = self._validate_relative_path(untrusted_path)
        candidate = self._root.joinpath(*parts)
        current = self._root
        for part in parts:
            current = current / part
            if self._is_link_or_junction(current):
                raise WorkspaceError(
                    WorkspaceErrorCode.LINK_TRAVERSAL,
                    "Workspace path traverses a link.",
                )

        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            raise WorkspaceError(
                WorkspaceErrorCode.NOT_FOUND,
                "Workspace file was not found.",
            ) from None
        except OSError:
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_PATH,
                "Workspace path could not be resolved.",
            ) from None

        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise WorkspaceError(
                WorkspaceErrorCode.OUTSIDE_WORKSPACE,
                "Requested path is outside the workspace.",
            ) from None

        try:
            mode = resolved.stat(follow_symlinks=False).st_mode
        except OSError:
            raise WorkspaceError(
                WorkspaceErrorCode.NOT_FOUND,
                "Workspace file was not found.",
            ) from None
        if not stat.S_ISREG(mode):
            raise WorkspaceError(
                WorkspaceErrorCode.WRONG_FILE_TYPE,
                "Workspace path is not a regular file.",
            )
        return resolved

    def relative_path(self, resolved_path: Path) -> str:
        try:
            relative = resolved_path.resolve(strict=True).relative_to(self._root)
        except (OSError, ValueError):
            raise WorkspaceError(
                WorkspaceErrorCode.OUTSIDE_WORKSPACE,
                "Requested path is outside the workspace.",
            ) from None
        return relative.as_posix()

    def _validate_relative_path(self, value: object) -> tuple[str, ...]:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > self._limits.max_path_chars
            or "\0" in value
            or "\\" in value
            or "%" in value
            or value.startswith("/")
            or _WINDOWS_DRIVE.match(value)
        ):
            raise self._invalid_path()
        parts = tuple(value.split("/"))
        if any(part in {"", ".", ".."} for part in parts):
            raise self._invalid_path()
        return parts

    @staticmethod
    def _is_link_or_junction(path: Path) -> bool:
        try:
            if path.is_symlink():
                return True
            is_junction = getattr(path, "is_junction", None)
            return bool(is_junction and is_junction())
        except OSError:
            return True

    @staticmethod
    def _invalid_path() -> WorkspaceError:
        return WorkspaceError(
            WorkspaceErrorCode.INVALID_PATH,
            "Workspace path is invalid.",
        )

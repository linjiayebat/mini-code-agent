from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from pydantic import ValidationError

from mini_code_agent.skills.models import (
    LoadedSkill,
    SkillDescriptor,
    SkillDiscoveryReport,
    SkillIssue,
    SkillIssueCode,
    SkillRoot,
    trust_for_source,
)
from mini_code_agent.skills.parser import SkillParseError, parse_skill_document

_MAX_FILE_BYTES = 262_144
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PUBLIC_MESSAGES = {
    SkillIssueCode.UNSAFE_ROOT: "Skill root is not a safe regular directory.",
    SkillIssueCode.ROOT_UNAVAILABLE: "Skill root is unavailable.",
    SkillIssueCode.UNSAFE_ENTRY: "Skill entry is not a safe regular file hierarchy.",
    SkillIssueCode.INVALID_ENCODING: "Skill document encoding is invalid.",
    SkillIssueCode.INVALID_DOCUMENT: "Skill document framing is invalid.",
    SkillIssueCode.INVALID_FRONTMATTER: "Skill frontmatter is invalid.",
    SkillIssueCode.INVALID_METADATA: "Skill metadata is invalid.",
    SkillIssueCode.INVALID_BODY: "Skill body is invalid.",
    SkillIssueCode.SKILL_TOO_LARGE: "Skill document exceeds a configured limit.",
    SkillIssueCode.CONFLICT: "Skill identity conflicts with another configured root.",
    SkillIssueCode.UNKNOWN_DISABLED_SKILL: "Disabled Skill identity was not discovered.",
}


class SkillCatalogError(ValueError):
    def __init__(self, code: SkillIssueCode) -> None:
        self.code = code
        super().__init__("Skill catalog configuration is invalid.")


class SkillLoadError(ValueError):
    def __init__(self, code: SkillIssueCode) -> None:
        self.code = code
        super().__init__("Skill content is unavailable.")


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    created_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> _FileIdentity:
        return cls(value.st_dev, value.st_ino, value.st_ctime_ns)


@dataclass(frozen=True, slots=True)
class _Entry:
    root: SkillRoot
    directory: Path
    path: Path
    descriptor: SkillDescriptor
    identity: _FileIdentity
    disabled: bool


@dataclass(frozen=True, slots=True)
class _Candidate:
    root: SkillRoot
    directory: Path
    name: str

    @property
    def skill_id(self) -> str:
        return f"{self.root.source.value}:{self.name}"


class SkillCatalog:
    def __init__(
        self,
        entries: Iterable[_Entry],
        report: SkillDiscoveryReport,
    ) -> None:
        ordered = tuple(sorted(entries, key=lambda item: item.descriptor.skill_id))
        self._entries = {item.descriptor.skill_id: item for item in ordered}
        self._report = report

    @classmethod
    def discover(
        cls,
        roots: Iterable[SkillRoot],
        *,
        disabled_ids: Iterable[str] = (),
        max_roots: int = 8,
        max_candidates: int = 128,
    ) -> tuple[SkillCatalog, SkillDiscoveryReport]:
        if not 1 <= max_roots <= 32 or not 1 <= max_candidates <= 512:
            raise SkillCatalogError(SkillIssueCode.LIMIT_EXCEEDED)
        root_values = tuple(islice(roots, max_roots + 1))
        if len(root_values) > max_roots:
            raise SkillCatalogError(SkillIssueCode.LIMIT_EXCEEDED)
        ordered_roots = tuple(
            sorted(root_values, key=lambda item: (item.source.value, item.root_id))
        )
        root_ids = tuple(root.root_id for root in ordered_roots)
        if len(root_ids) != len(set(root_ids)):
            raise SkillCatalogError(SkillIssueCode.LIMIT_EXCEEDED)

        disabled_values = tuple(islice(disabled_ids, 65))
        if len(disabled_values) > 64:
            raise SkillCatalogError(SkillIssueCode.LIMIT_EXCEEDED)
        disabled = frozenset(disabled_values)
        issues: list[SkillIssue] = []
        candidates: list[_Candidate] = []
        for root in ordered_roots:
            root_code = _validate_directory(root.path, root=True)
            if root_code is not None:
                issues.append(_issue(root, root_code))
                continue
            try:
                with os.scandir(root.path) as iterator:
                    children = tuple(islice(iterator, 513))
            except OSError:
                issues.append(_issue(root, SkillIssueCode.ROOT_UNAVAILABLE))
                continue
            if len(children) > 512:
                raise SkillCatalogError(SkillIssueCode.LIMIT_EXCEEDED)
            children = tuple(sorted(children, key=lambda item: item.name))
            for child in children:
                try:
                    details = child.stat(follow_symlinks=False)
                except OSError:
                    issues.append(_issue(root, SkillIssueCode.UNSAFE_ENTRY))
                    continue
                if _is_link_or_reparse(details):
                    issues.append(
                        _issue(
                            root, SkillIssueCode.UNSAFE_ENTRY, _possible_skill_id(root, child.name)
                        )
                    )
                    continue
                if not stat.S_ISDIR(details.st_mode):
                    continue
                candidates.append(_Candidate(root, Path(child.path), child.name))
                if len(candidates) > max_candidates:
                    raise SkillCatalogError(SkillIssueCode.LIMIT_EXCEEDED)

        parsed_entries: list[_Entry] = []
        for candidate in candidates:
            if _possible_skill_id(candidate.root, candidate.name) is None:
                issues.append(_issue(candidate.root, SkillIssueCode.INVALID_METADATA))
                continue
            file_path = candidate.directory / "SKILL.md"
            code = _validate_directory(candidate.directory)
            if code is None:
                code = _validate_regular_file(file_path)
            if code is not None:
                issues.append(_issue(candidate.root, code, candidate.skill_id))
                continue
            try:
                raw, identity = _read_stable_file(file_path)
                parsed = parse_skill_document(raw, directory_name=candidate.name)
            except SkillParseError as exc:
                issues.append(_issue(candidate.root, exc.code, candidate.skill_id))
                continue
            except OSError:
                issues.append(
                    _issue(candidate.root, SkillIssueCode.UNSAFE_ENTRY, candidate.skill_id)
                )
                continue
            descriptor = SkillDescriptor(
                skill_id=candidate.skill_id,
                name=parsed.metadata.name,
                source=candidate.root.source,
                trust=trust_for_source(candidate.root.source),
                description=parsed.metadata.description,
                version=parsed.metadata.version,
                model_invocable=parsed.metadata.model_invocable,
                relative_path=f"{candidate.name}/SKILL.md",
                byte_count=parsed.byte_count,
                sha256=parsed.sha256,
            )
            parsed_entries.append(
                _Entry(
                    root=candidate.root,
                    directory=candidate.directory,
                    path=file_path,
                    descriptor=descriptor,
                    identity=identity,
                    disabled=descriptor.skill_id in disabled,
                )
            )

        counts = Counter(entry.descriptor.skill_id for entry in parsed_entries)
        admitted: list[_Entry] = []
        for entry in sorted(
            parsed_entries,
            key=lambda item: (item.descriptor.skill_id, item.root.root_id),
        ):
            if counts[entry.descriptor.skill_id] > 1:
                issues.append(
                    _issue(entry.root, SkillIssueCode.CONFLICT, entry.descriptor.skill_id)
                )
            else:
                admitted.append(entry)

        discovered_ids = frozenset(entry.descriptor.skill_id for entry in admitted)
        for skill_id in sorted(disabled - discovered_ids):
            try:
                issue = SkillIssue(
                    root_id="configuration",
                    skill_id=skill_id,
                    code=SkillIssueCode.UNKNOWN_DISABLED_SKILL,
                    message=_PUBLIC_MESSAGES[SkillIssueCode.UNKNOWN_DISABLED_SKILL],
                )
            except ValidationError:
                issue = SkillIssue(
                    root_id="configuration",
                    skill_id=None,
                    code=SkillIssueCode.UNKNOWN_DISABLED_SKILL,
                    message=_PUBLIC_MESSAGES[SkillIssueCode.UNKNOWN_DISABLED_SKILL],
                )
            issues.append(issue)

        visible = tuple(
            entry.descriptor
            for entry in sorted(admitted, key=lambda item: item.descriptor.skill_id)
            if not entry.disabled
        )
        report = SkillDiscoveryReport(
            skills=visible,
            issues=tuple(
                sorted(
                    issues,
                    key=lambda item: (
                        item.root_id,
                        item.skill_id or "",
                        item.code.value,
                    ),
                )
            ),
        )
        return cls(admitted, report), report

    @property
    def report(self) -> SkillDiscoveryReport:
        return self._report

    @property
    def model_descriptors(self) -> tuple[SkillDescriptor, ...]:
        return tuple(
            entry.descriptor
            for entry in self._entries.values()
            if not entry.disabled and entry.descriptor.model_invocable
        )

    def descriptor(self, skill_id: str) -> SkillDescriptor | None:
        entry = self._entries.get(skill_id)
        return None if entry is None else entry.descriptor

    def load(self, skill_id: str, *, expected_sha256: str) -> LoadedSkill:
        entry = self._entries.get(skill_id)
        if entry is None:
            raise SkillLoadError(SkillIssueCode.UNKNOWN_SKILL)
        if entry.disabled:
            raise SkillLoadError(SkillIssueCode.SKILL_DISABLED)
        if not entry.descriptor.model_invocable:
            raise SkillLoadError(SkillIssueCode.NOT_MODEL_INVOCABLE)
        if expected_sha256 != entry.descriptor.sha256:
            raise SkillLoadError(SkillIssueCode.SKILL_CHANGED)
        try:
            if _validate_directory(entry.root.path, root=True) is not None:
                raise OSError
            if _validate_directory(entry.directory) is not None:
                raise OSError
            if _validate_regular_file(entry.path) is not None:
                raise OSError
            raw, identity = _read_stable_file(entry.path)
            if identity != entry.identity:
                raise OSError
            parsed = parse_skill_document(raw, directory_name=entry.descriptor.name)
        except (OSError, SkillParseError):
            raise SkillLoadError(SkillIssueCode.SKILL_CHANGED) from None
        if (
            parsed.sha256 != entry.descriptor.sha256
            or parsed.byte_count != entry.descriptor.byte_count
            or parsed.metadata.name != entry.descriptor.name
            or parsed.metadata.description != entry.descriptor.description
            or parsed.metadata.version != entry.descriptor.version
            or parsed.metadata.model_invocable != entry.descriptor.model_invocable
        ):
            raise SkillLoadError(SkillIssueCode.SKILL_CHANGED)
        return LoadedSkill(descriptor=entry.descriptor, content=parsed.body)


def _possible_skill_id(root: SkillRoot, name: str) -> str | None:
    try:
        descriptor = SkillDescriptor(
            skill_id=f"{root.source.value}:{name}",
            name=name,
            source=root.source,
            trust=trust_for_source(root.source),
            description="candidate",
            version="0.0.0",
            model_invocable=True,
            relative_path=f"{name}/SKILL.md",
            byte_count=1,
            sha256="0" * 64,
        )
    except ValueError:
        return None
    return descriptor.skill_id


def _issue(
    root: SkillRoot,
    code: SkillIssueCode,
    skill_id: str | None = None,
) -> SkillIssue:
    normalized = (
        SkillIssueCode.ROOT_UNAVAILABLE if code is SkillIssueCode.ROOT_UNAVAILABLE else code
    )
    return SkillIssue(
        root_id=root.root_id,
        skill_id=skill_id,
        code=normalized,
        message=_PUBLIC_MESSAGES.get(normalized, "Skill entry is invalid."),
    )


def _validate_directory(path: Path, *, root: bool = False) -> SkillIssueCode | None:
    unavailable = SkillIssueCode.ROOT_UNAVAILABLE if root else SkillIssueCode.UNSAFE_ENTRY
    unsafe = SkillIssueCode.UNSAFE_ROOT if root else SkillIssueCode.UNSAFE_ENTRY
    try:
        details = os.lstat(path)
        resolved = path.resolve(strict=True)
    except OSError:
        return unavailable
    if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
        return unsafe
    if os.path.normcase(str(resolved)) != os.path.normcase(str(path.absolute())):
        return unsafe
    return None


def _validate_regular_file(path: Path) -> SkillIssueCode | None:
    try:
        details = os.lstat(path)
    except OSError:
        return SkillIssueCode.UNSAFE_ENTRY
    if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
        return SkillIssueCode.UNSAFE_ENTRY
    return None


def _is_link_or_reparse(details: os.stat_result) -> bool:
    attributes = int(getattr(details, "st_file_attributes", 0))
    return stat.S_ISLNK(details.st_mode) or bool(attributes & _REPARSE_POINT)


def _read_stable_file(path: Path) -> tuple[bytes, _FileIdentity]:
    before = os.lstat(path)
    if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise OSError
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not _same_file_object(before, opened):
            raise OSError
        raw = stream.read(_MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > _MAX_FILE_BYTES or not _same_file_object(opened, after):
        raise OSError
    return raw, _FileIdentity.from_stat(opened)


def _same_file_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)

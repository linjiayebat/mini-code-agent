from __future__ import annotations

import os
from pathlib import Path

import pytest

from mini_code_agent.skills.catalog import SkillCatalog, SkillCatalogError, SkillLoadError
from mini_code_agent.skills.models import (
    SkillDescriptor,
    SkillIssueCode,
    SkillRoot,
    SkillSource,
    SkillTrust,
)


def root_for(path: Path, source: SkillSource, root_id: str) -> SkillRoot:
    path.mkdir(parents=True, exist_ok=True)
    return SkillRoot(path=path.resolve(), source=source, root_id=root_id)


def write_skill(
    root: Path,
    name: str,
    *,
    body: str = "Inspect tests first.",
    model_invocable: bool = True,
    version: str = "1.0.0",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Review with {name}.\n"
        f"version: {version}\n"
        f"model_invocable: {'true' if model_invocable else 'false'}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def discovered_skill(
    tmp_path: Path,
    *,
    model_invocable: bool = True,
    disabled_ids: tuple[str, ...] = (),
) -> tuple[SkillCatalog, SkillDescriptor, Path]:
    root = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    path = write_skill(root.path, "review-python", model_invocable=model_invocable)
    catalog, _report = SkillCatalog.discover((root,), disabled_ids=disabled_ids)
    descriptor = catalog.descriptor("project:review-python")
    assert descriptor is not None
    return catalog, descriptor, path


def test_cross_source_names_coexist_without_shadowing(tmp_path: Path) -> None:
    user = root_for(tmp_path / "user", SkillSource.USER, "user-main")
    project = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    write_skill(user.path, "review-python")
    write_skill(project.path, "review-python")

    catalog, report = SkillCatalog.discover((user, project))

    assert tuple(item.skill_id for item in report.skills) == (
        "project:review-python",
        "user:review-python",
    )
    assert catalog.descriptor("project:review-python").trust is SkillTrust.UNTRUSTED_PROJECT  # type: ignore[union-attr]
    assert catalog.descriptor("user:review-python").trust is SkillTrust.USER  # type: ignore[union-attr]


def test_same_source_conflict_quarantines_every_candidate(tmp_path: Path) -> None:
    first = root_for(tmp_path / "first", SkillSource.USER, "user-first")
    second = root_for(tmp_path / "second", SkillSource.USER, "user-second")
    write_skill(first.path, "review-python")
    write_skill(second.path, "review-python")

    catalog, report = SkillCatalog.discover((second, first))

    assert report.skills == ()
    assert catalog.descriptor("user:review-python") is None
    assert [issue.code for issue in report.issues] == [
        SkillIssueCode.CONFLICT,
        SkillIssueCode.CONFLICT,
    ]


def test_invalid_entry_is_quarantined_without_hiding_valid_skill(tmp_path: Path) -> None:
    root = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    write_skill(root.path, "valid-skill")
    invalid = write_skill(root.path, "invalid-skill")
    invalid.write_text("---\nname: invalid-skill\n---\nbody", encoding="utf-8")

    _, report = SkillCatalog.discover((root,))

    assert [item.skill_id for item in report.skills] == ["project:valid-skill"]
    assert len(report.issues) == 1
    assert report.issues[0].code is SkillIssueCode.INVALID_METADATA
    assert str(tmp_path) not in report.issues[0].message


def test_discovery_is_direct_child_only(tmp_path: Path) -> None:
    root = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    write_skill(root.path, "top-level")
    nested = root.path / "container"
    write_skill(nested, "nested-skill")

    _, report = SkillCatalog.discover((root,))

    assert [item.skill_id for item in report.skills] == ["project:top-level"]
    assert any(issue.skill_id == "project:container" for issue in report.issues)


def test_disabled_and_non_model_skills_are_not_model_visible(tmp_path: Path) -> None:
    root = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    write_skill(root.path, "disabled")
    write_skill(root.path, "user-only", model_invocable=False)
    catalog, report = SkillCatalog.discover(
        (root,),
        disabled_ids=("project:disabled", "project:missing"),
    )

    assert [item.skill_id for item in report.skills] == ["project:user-only"]
    assert catalog.model_descriptors == ()
    assert any(issue.code is SkillIssueCode.UNKNOWN_DISABLED_SKILL for issue in report.issues)


def test_root_and_candidate_limits_fail_before_partial_catalog(tmp_path: Path) -> None:
    first = root_for(tmp_path / "first", SkillSource.USER, "first")
    second = root_for(tmp_path / "second", SkillSource.USER, "second")
    with pytest.raises(SkillCatalogError) as roots:
        SkillCatalog.discover((first, second), max_roots=1)
    assert roots.value.code is SkillIssueCode.LIMIT_EXCEEDED

    write_skill(first.path, "one")
    write_skill(first.path, "two")
    with pytest.raises(SkillCatalogError) as candidates:
        SkillCatalog.discover((first,), max_candidates=1)
    assert candidates.value.code is SkillIssueCode.LIMIT_EXCEEDED


def test_disabled_and_directory_entry_counts_are_bounded(tmp_path: Path) -> None:
    root = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    with pytest.raises(SkillCatalogError) as disabled:
        SkillCatalog.discover(
            (root,),
            disabled_ids=tuple(f"project:skill-{index}" for index in range(65)),
        )
    assert disabled.value.code is SkillIssueCode.LIMIT_EXCEEDED

    for index in range(513):
        (root.path / f"unrelated-{index}.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SkillCatalogError) as entries:
        SkillCatalog.discover((root,))
    assert entries.value.code is SkillIssueCode.LIMIT_EXCEEDED


def test_unsafe_or_missing_root_contributes_no_skills(tmp_path: Path) -> None:
    missing = SkillRoot(
        path=(tmp_path / "missing").resolve(),
        source=SkillSource.PROJECT,
        root_id="missing",
    )
    _, report = SkillCatalog.discover((missing,))
    assert report.skills == ()
    assert report.issues[0].code is SkillIssueCode.ROOT_UNAVAILABLE


def test_linked_skill_file_is_rejected_when_links_are_available(tmp_path: Path) -> None:
    root = root_for(tmp_path / "project", SkillSource.PROJECT, "project-main")
    target = tmp_path / "target.md"
    target.write_text("---\nname: linked\n---\nbody", encoding="utf-8")
    directory = root.path / "linked"
    directory.mkdir()
    try:
        (directory / "SKILL.md").symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink unavailable in this environment: {exc}")

    _, report = SkillCatalog.discover((root,))

    assert report.skills == ()
    assert report.issues[0].code is SkillIssueCode.UNSAFE_ENTRY


def test_load_returns_unchanged_labelled_content(tmp_path: Path) -> None:
    catalog, descriptor, _ = discovered_skill(tmp_path)

    loaded = catalog.load(descriptor.skill_id, expected_sha256=descriptor.sha256)  # type: ignore[attr-defined]

    assert loaded.descriptor == descriptor
    assert loaded.content == "Inspect tests first.\n"
    assert loaded.content_type == "untrusted_markdown"


@pytest.mark.parametrize("change", ["body", "metadata", "replace", "delete"])
def test_load_rejects_discovery_drift(tmp_path: Path, change: str) -> None:
    catalog, descriptor, path = discovered_skill(tmp_path)
    if change == "body":
        write_skill(path.parents[1], "review-python", body="Changed instructions.")
    elif change == "metadata":
        write_skill(path.parents[1], "review-python", version="1.0.1")
    elif change == "replace":
        raw = path.read_bytes()
        path.unlink()
        path.write_bytes(raw)
    else:
        path.unlink()

    with pytest.raises(SkillLoadError) as caught:
        catalog.load(descriptor.skill_id, expected_sha256=descriptor.sha256)  # type: ignore[attr-defined]

    assert caught.value.code is SkillIssueCode.SKILL_CHANGED
    assert str(tmp_path) not in str(caught.value)


def test_load_rejects_stale_expected_hash_before_reading(tmp_path: Path) -> None:
    catalog, descriptor, path = discovered_skill(tmp_path)
    path.unlink()

    with pytest.raises(SkillLoadError) as caught:
        catalog.load(descriptor.skill_id, expected_sha256="0" * 64)  # type: ignore[attr-defined]

    assert caught.value.code is SkillIssueCode.SKILL_CHANGED


def test_load_rejects_unknown_disabled_and_non_model_skill(tmp_path: Path) -> None:
    catalog, descriptor, _ = discovered_skill(tmp_path, disabled_ids=("project:review-python",))
    with pytest.raises(SkillLoadError) as disabled:
        catalog.load(descriptor.skill_id, expected_sha256=descriptor.sha256)  # type: ignore[attr-defined]
    assert disabled.value.code is SkillIssueCode.SKILL_DISABLED

    hidden_catalog, hidden_descriptor, _ = discovered_skill(
        tmp_path / "hidden",
        model_invocable=False,
    )
    with pytest.raises(SkillLoadError) as hidden:
        hidden_catalog.load(  # type: ignore[attr-defined]
            hidden_descriptor.skill_id,  # type: ignore[attr-defined]
            expected_sha256=hidden_descriptor.sha256,  # type: ignore[attr-defined]
        )
    assert hidden.value.code is SkillIssueCode.NOT_MODEL_INVOCABLE

    with pytest.raises(SkillLoadError) as unknown:
        catalog.load("project:missing", expected_sha256="0" * 64)
    assert unknown.value.code is SkillIssueCode.UNKNOWN_SKILL


def test_load_rejects_link_replacement_when_available(tmp_path: Path) -> None:
    catalog, descriptor, path = discovered_skill(tmp_path)
    target = tmp_path / "same.md"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink unavailable in this environment: {exc}")

    with pytest.raises(SkillLoadError) as caught:
        catalog.load(descriptor.skill_id, expected_sha256=descriptor.sha256)  # type: ignore[attr-defined]
    assert caught.value.code is SkillIssueCode.SKILL_CHANGED


def test_discovery_rejects_duplicate_root_ids(tmp_path: Path) -> None:
    first = root_for(tmp_path / "first", SkillSource.USER, "duplicate")
    second = root_for(tmp_path / "second", SkillSource.PROJECT, "duplicate")
    with pytest.raises(SkillCatalogError) as caught:
        SkillCatalog.discover((first, second))
    assert caught.value.code is SkillIssueCode.LIMIT_EXCEEDED


def test_regular_file_identity_uses_stat_fields(tmp_path: Path) -> None:
    _, _, path = discovered_skill(tmp_path)
    details = os.stat(path)
    assert details.st_size > 0
    assert details.st_ino >= 0

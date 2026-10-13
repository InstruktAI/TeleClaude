"""Agent-artifact validation and path-scoped artifact selection."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import frontmatter

from teleclaude import agent_artifacts
from teleclaude.constants import ArtifactKind
from teleclaude.docs_publishers import publisher_resolution
from teleclaude.resource_validation._models import _ARTIFACT_REF_ORDER, _as_str_list, _error
from teleclaude.resource_validation._snippet import resolve_ref_path

_NAME_FIELD = "name"
_DESCRIPTION_FIELD = "description"
_MISSING_FIELD_TEMPLATE = "{kind} {path} is missing frontmatter '{field}'"
_UTF8 = "utf-8"
_SKILL_NAME_MISMATCH = "Skill name '{name}' must match folder '{dirname}'"

__all__ = [
    "_ARTIFACT_REF_ORDER",
    "_as_str_list",
    "_error",
    "validate_all_artifacts",
    "validate_artifact",
    "validate_artifact_frontmatter",
    "validate_artifact_refs_exist",
]


def validate_artifact_frontmatter(post: frontmatter.Post, path: str, *, kind: ArtifactKind) -> None:
    """Validate the identity frontmatter of a skill entrypoint: ``name`` and ``description``."""
    description = post.metadata.get(_DESCRIPTION_FIELD)
    if not isinstance(description, str) or not description.strip():
        raise ValueError(_MISSING_FIELD_TEMPLATE.format(kind=kind.title(), path=path, field=_DESCRIPTION_FIELD))
    name = post.metadata.get(_NAME_FIELD)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(_MISSING_FIELD_TEMPLATE.format(kind=kind.title(), path=path, field=_NAME_FIELD))


def validate_artifact_refs_exist(refs: list[str], path: str, *, project_root: Path) -> None:
    """Raise if any artifact ``@`` ref points to a non-existent file."""
    current_path = Path(path)
    for ref in refs:
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            raise ValueError(f"{path} references non-existent file: {ref}")


def _validate_skill_folder_identity(post: frontmatter.Post, path: str) -> None:
    name = post.metadata.get(_NAME_FIELD)
    dirname = Path(path).parent.name
    if isinstance(name, str) and name != dirname:
        raise ValueError(_SKILL_NAME_MISMATCH.format(name=name, dirname=dirname))


def validate_artifact(post: frontmatter.Post, path: str, *, kind: ArtifactKind, project_root: Path) -> None:
    """Full validation of a skill entrypoint: identity metadata and folder identity; the body stays pass-through."""
    del project_root
    validate_artifact_frontmatter(post, path, kind=kind)
    _validate_skill_folder_identity(post, path)


def _selected_artifacts(
    project_root: Path, paths: Sequence[Path | str]
) -> tuple[list[tuple[Path, ArtifactKind, Path]], list[str]]:
    """Classify each requested path, returning validatable artifacts and findings.

    A path with no registry boundary at all (``UnclassifiedSourceError``) and a
    classified path outside its declared reach both become findings rather
    than being skipped — UC-ARD32 requires refusal, never a silent fallback.
    """
    selected: dict[Path, tuple[ArtifactKind, Path]] = {}
    findings: list[str] = []
    reach_facts = agent_artifacts.ReachFacts(project_root)
    classifier = agent_artifacts.ArtifactClassifier(project_root)
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        try:
            source = classifier.classify(path)
        except agent_artifacts.UnclassifiedSourceError as exc:
            findings.append(str(exc))
            continue
        if source is None:
            continue
        violation = agent_artifacts.reach_violation(project_root, source, reach_facts)
        if violation is not None:
            findings.append(violation)
            continue
        if source.kind is not None:
            selected[source.entrypoint.resolve(strict=False)] = (source.kind, project_root)
    return [(path, kind, owner) for path, (kind, owner) in selected.items()], findings


def _all_artifacts(project_root: Path) -> tuple[list[tuple[Path, ArtifactKind, Path]], list[str]]:
    """Enumerate every registry-classified artifact plus every boundary/reach finding.

    ``boundary_violations`` covers what a repo-wide scan would otherwise never
    see: an unrecognized kind directory is not enumerated as a source by
    anything, so nothing here would ever probe it directly.
    """
    artifacts: dict[Path, tuple[ArtifactKind, Path]] = {}
    findings: list[str] = list(agent_artifacts.boundary_violations(project_root))
    reach_facts = agent_artifacts.ReachFacts(project_root)
    for source in agent_artifacts.all_sources(project_root):
        violation = agent_artifacts.reach_violation(project_root, source, reach_facts)
        if violation is not None:
            findings.append(violation)
            continue
        if source.kind is not None:
            artifacts[source.entrypoint.resolve(strict=False)] = (source.kind, project_root)
    return [(path, kind, owner) for path, (kind, owner) in artifacts.items()], findings


def validate_all_artifacts(project_root: Path, *, paths: Sequence[Path | str] | None = None) -> list[str]:
    """Validate all artifacts, or only artifacts selected by ``paths``.

    The pass reads publisher ownership once, so every reference it resolves shares one registry.
    """
    try:
        with publisher_resolution(project_root):
            return _validate_artifacts(project_root, paths)
    except ValueError as exc:
        return [str(exc)]


def _validate_artifacts(project_root: Path, paths: Sequence[Path | str] | None) -> list[str]:
    artifacts, errors = _all_artifacts(project_root) if paths is None else _selected_artifacts(project_root, paths)
    for entrypoint, kind, owner_root in artifacts:
        if not entrypoint.is_file():
            continue
        try:
            with entrypoint.open(encoding=_UTF8) as file_obj:
                post = frontmatter.load(file_obj)
            validate_artifact(post, str(entrypoint), kind=kind, project_root=owner_root)
        except Exception as exc:
            errors.append(str(exc))
    return errors

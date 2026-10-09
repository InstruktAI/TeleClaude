"""Agent-artifact validation and path-scoped artifact selection."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import frontmatter

from teleclaude import agent_artifacts
from teleclaude.constants import ArtifactKind
from teleclaude.docs_publishers import publisher_resolution
from teleclaude.resource_validation._models import (
    _ARTIFACT_REF_ORDER,
    _as_str_list,
    _error,
    _first_out_of_order_ref,
)
from teleclaude.resource_validation._snippet import INCLUDE_DIRECTIVE_RE, resolve_ref_path

_NAME_FIELD = "name"
_UTF8 = "utf-8"
_SKILL_NAME_MISMATCH = "Skill name '{name}' must match folder '{dirname}'"

__all__ = [
    "_ARTIFACT_REF_ORDER",
    "_as_str_list",
    "_error",
    "validate_all_artifacts",
    "validate_artifact",
    "validate_artifact_body",
    "validate_artifact_frontmatter",
    "validate_artifact_refs_exist",
]


def _extract_artifact_required_reads(lines: list[str]) -> list[str]:
    """Extract ``@`` refs from a Required reads section after the H1 title."""
    refs: list[str] = []
    in_required_reads = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if stripped.startswith("## ") or stripped.startswith("# "):
                break
            if stripped.startswith("@"):
                refs.append(stripped[1:].strip())
                continue
            if stripped.startswith("- @"):
                refs.append(stripped[3:].strip())
                continue
            if not stripped:
                continue
            break
    return refs


def _next_nonblank(lines: list[str], idx: int) -> tuple[str | None, int]:
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, idx
    return lines[idx], idx


def validate_artifact_frontmatter(post: frontmatter.Post, path: str, *, kind: ArtifactKind) -> None:
    """Validate frontmatter fields for an agent artifact."""
    description = post.metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{kind.title()} {path} is missing frontmatter 'description'")
    if kind == ArtifactKind.SKILL:
        name = post.metadata.get(_NAME_FIELD)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Skill {path} is missing frontmatter 'name'")
    parameters = post.metadata.get("parameters")
    if parameters is not None:
        _validate_parameters_field(parameters, path)


def _validate_parameters_field(parameters: object, path: str) -> None:
    """Validate the ``parameters`` frontmatter field shape."""
    if not isinstance(parameters, list):
        raise ValueError(f"{path} frontmatter 'parameters' must be a list")
    seen_names: set[str] = set()
    for param in parameters:
        if not isinstance(param, dict):
            raise ValueError(f"{path} each parameter must be a mapping")
        name = param.get(_NAME_FIELD)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path} each parameter must have a 'name' string")
        if name in seen_names:
            raise ValueError(f"{path} duplicate parameter name '{name}'")
        seen_names.add(name)


def _validate_artifact_argument_hint(post: frontmatter.Post, path: str, *, kind: ArtifactKind) -> None:
    argument_hint = post.metadata.get("argument-hint")
    if kind == ArtifactKind.COMMAND and argument_hint is not None and not isinstance(argument_hint, str):
        raise ValueError(f"{path} has invalid frontmatter 'argument-hint' (must be a string)")


def _find_required_reads_block(lines: list[str], h1_idx: int) -> tuple[int | None, int | None]:
    required_reads_idx = None
    required_reads_end = None
    for index in range(h1_idx + 1, len(lines)):
        if lines[index].strip().lower() != "## required reads":
            continue
        required_reads_idx = index
        end = index + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if not stripped or stripped.startswith("@") or stripped.startswith("- @"):
                end += 1
                continue
            if stripped.startswith("# ") or stripped.startswith("## "):
                break
            break
        required_reads_end = end
        break
    return required_reads_idx, required_reads_end


def _validate_required_reads_block_position(
    lines: list[str], path: str, *, h1_idx: int, required_reads_idx: int | None, required_reads_end: int | None
) -> None:
    if required_reads_idx is None:
        return
    for index in range(h1_idx + 1, required_reads_idx):
        if lines[index].strip().startswith("## "):
            raise ValueError(f"{path} must place Required reads before other H2 sections")
    for index in range(required_reads_idx + 1, required_reads_end or len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("@") or stripped.startswith("- @"):
            continue
        break


def _find_first_artifact_section(lines: list[str], h1_idx: int) -> int | None:
    for index in range(h1_idx + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("## ") and stripped.lower() != "## required reads":
            return index
    return None


def _validate_artifact_role_activation(
    lines: list[str], path: str, *, kind: ArtifactKind, h1_idx: int, first_section_idx: int
) -> None:
    role_lines = [line.strip() for line in lines]
    if kind == ArtifactKind.COMMAND:
        has_role = any(line.startswith("You are now the ") for line in role_lines[h1_idx + 1 : first_section_idx])
        if not has_role:
            raise ValueError(f"{path} must include a role activation line before the first section")
        return
    if any(line.startswith("You are now the ") for line in role_lines):
        raise ValueError(f"{path} must not include a role activation line")


def _artifact_section_order(kind: ArtifactKind) -> list[str]:
    if kind == ArtifactKind.COMMAND:
        return ["Purpose", "Inputs", "Outputs", "Steps", "Discipline"]
    return ["Purpose", "Scope", "Inputs", "Outputs", "Procedure"]


def _collect_artifact_headings(lines: list[str], path: str, *, h1_idx: int) -> list[str]:
    headings: list[str] = []
    in_required_reads = False
    in_code_fence = False
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped.lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if stripped.startswith("## ") or stripped.startswith("# "):
                in_required_reads = False
            else:
                continue
        if stripped.startswith("@") or stripped.startswith("- @"):
            raise ValueError(f"{path} has inline refs outside the required reads block")
        if stripped.startswith("# "):
            if index != h1_idx:
                raise ValueError(f"{path} must only have one H1 title")
            continue
        if stripped.startswith("### "):
            raise ValueError(f"{path} must use H2 headings only for schema sections")
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if title.lower() != "required reads":
                headings.append(title)
    return headings


def _is_ordered_subset(headings: list[str], required: list[str]) -> bool:
    cursor = iter(required)
    return all(heading in cursor for heading in headings)


def _validate_artifact_section_order(lines: list[str], path: str, *, kind: ArtifactKind, h1_idx: int) -> None:
    headings = _collect_artifact_headings(lines, path, h1_idx=h1_idx)
    if not headings:
        raise ValueError(f"{path} is missing required section headings")
    required = _artifact_section_order(kind)
    for heading in headings:
        if heading not in required:
            raise ValueError(f"{path} has invalid section heading '{heading}'")
    if kind == ArtifactKind.COMMAND:
        if not _is_ordered_subset(headings, required):
            raise ValueError(f"{path} sections must follow the order: {' → '.join(required)}")
    elif headings != required:
        raise ValueError(f"{path} section order must be: {' → '.join(required)}")


def validate_artifact_body(post: frontmatter.Post, path: str, *, kind: ArtifactKind) -> None:
    """Validate body structure of a command artifact."""
    if kind == ArtifactKind.SKILL:
        return
    _validate_artifact_argument_hint(post, path, kind=kind)
    lines = post.content.splitlines()
    first_line, h1_idx = _next_nonblank(lines, 0)
    if first_line is None or not first_line.startswith("# "):
        raise ValueError(f"{path} must start with an H1 title")
    required_reads_idx, required_reads_end = _find_required_reads_block(lines, h1_idx)
    _validate_required_reads_block_position(
        lines, path, h1_idx=h1_idx, required_reads_idx=required_reads_idx, required_reads_end=required_reads_end
    )
    _validate_required_reads_order(_extract_artifact_required_reads(lines), path)
    first_section_idx = _find_first_artifact_section(lines, h1_idx)
    if first_section_idx is None:
        raise ValueError(f"{path} is missing required section headings")
    _validate_artifact_role_activation(lines, path, kind=kind, h1_idx=h1_idx, first_section_idx=first_section_idx)
    _validate_artifact_section_order(lines, path, kind=kind, h1_idx=h1_idx)


def _validate_required_reads_order(refs: list[str], path: str) -> None:
    if _first_out_of_order_ref(refs) is not None:
        raise ValueError(f"{path} required reads are out of order; expected {' → '.join(_ARTIFACT_REF_ORDER)}")


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
    """Full validation of an agent artifact."""
    validate_artifact_frontmatter(post, path, kind=kind)
    if kind == ArtifactKind.SKILL:
        _validate_skill_folder_identity(post, path)
        return
    validate_artifact_body(post, path, kind=kind)
    refs = _extract_artifact_required_reads(post.content.splitlines())
    if refs:
        validate_artifact_refs_exist(refs, path, project_root=project_root)
    include_refs = INCLUDE_DIRECTIVE_RE.findall(post.content)
    if include_refs:
        validate_artifact_refs_exist(include_refs, path, project_root=project_root)


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

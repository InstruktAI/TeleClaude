"""Context-owned registry of agent-artifact sources.

One answer to "what is an agent-artifact source, and who may publish it?" for
every consumer that used to carry its own local tuple or glob: artifact
validation, checkpoint/watch scope, onboarding capability inference,
slug-worktree source protection, and sealed-commit review routing. See
``projects/teleclaude/design/architecture/agent-artifact-distribution`` for the approved
design this registry implements.

``.agents/`` is never a source — it is the delivery location the local phase
writes to and other agent CLIs read from. Only paths under a project's
``AGENTS.master.md`` and ``agents/`` tree are ever classified here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryFile

from teleclaude.constants import AGENT_ARTIFACT_SOURCE_GLOBS, ArtifactKind
from teleclaude.docs_publishers import git_common_root
from teleclaude.domains import publishes_for_root
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT
from teleclaude.snippet_validation import companion_shape, is_retirement_companion

__all__ = [
    "AGENT_ARTIFACT_ROOT_DIRNAME",
    "AGENT_ARTIFACT_SOURCE_GLOBS",
    "ArtifactAuthorship",
    "ArtifactReach",
    "ArtifactSource",
    "ArtifactTier",
    "CommandRetirementCompanion",
    "UnclassifiedSourceError",
    "all_sources",
    "boundary_violations",
    "classify_candidate",
    "command_source_roots",
    "is_mother_project",
    "project_commands_root",
    "project_skills_root",
    "reach_ok",
    "reach_violation",
    "retirement_command_companions",
]

AGENT_ARTIFACT_ROOT_DIRNAME = "agents"
_PROJECT_MASTER_FILENAME = "AGENTS.master.md"
_GLOBAL_MASTER_FILENAME = "AGENTS.master.md"
_GLOBAL_BASELINE_FILENAME = "AGENTS.global.md"
_ADDENDUM_SUFFIX = ".addendum.md"
_GLOBAL_DIRNAME = "global"
_LOCAL_DIRNAME = "local"
_COMMANDS_DIRNAME = "commands"
_SKILLS_DIRNAME = "skills"
_SKILL_ENTRYPOINT_FILENAME = "SKILL.md"
_MARKDOWN_SUFFIX = ".md"
_MALFORMED_COMMAND_SOURCE_TEMPLATE = "{path} is a malformed command source companion"
_GIT_CHECK_IGNORE_ARGUMENTS = ("-z", "--stdin")
_GIT_CHECK_IGNORE_NOT_IGNORED_STATUS = 1
_GIT_IGNORE_QUERY_FAILURE_TEMPLATE = "Could not determine ignored agent-artifact boundary entries: {error}"
# The generated entrypoint `_write_project_agents` writes next to
# `agents/AGENTS.master.md` — never an authored source, but an expected,
# sanctioned presence, not a boundary violation. It is gitignored.
_GENERATED_ROOT_ENTRYPOINT_FILENAME = "AGENTS.md"


class ArtifactTier(StrEnum):
    """Where a source sits in the tiered layout."""

    ROOT = "root"
    GLOBAL = "global"
    PROJECT = "project"


class ArtifactAuthorship(StrEnum):
    """Whether TeleClaude owns the content or merely incorporates it."""

    AUTHORED = "authored"
    INCORPORATED = "incorporated"


class ArtifactReach(StrEnum):
    """Who may publish a source at this location."""

    SELF = "self"
    MOTHER_ONLY = "mother_only"
    DOMAIN = "domain"


@dataclass(frozen=True)
class ArtifactSource:
    """One classified agent-artifact source path.

    ``kind`` is ``None`` for a root-tier master/addendum/global-baseline file:
    these are locked wrappers, not commands or skills, and carry no
    structural body validation. ``domain`` is populated only for a
    ``ArtifactReach.DOMAIN`` global command.
    """

    entrypoint: Path
    tier: ArtifactTier
    authorship: ArtifactAuthorship
    reach: ArtifactReach
    kind: ArtifactKind | None = None
    domain: str | None = None


@dataclass(frozen=True)
class CommandRetirementCompanion:
    """A zero-byte command companion and its command source identity."""

    companion_path: Path
    command_path: Path
    slug: str


class UnclassifiedSourceError(ValueError):
    """A candidate path sits under a recognized tier root but matches no boundary.

    Distinct from ``None`` (the path is not an agent-artifact source at all):
    an unrecognized kind directory or stray top-level entry inside ``agents/``
    must fail the caller rather than be treated as absent — see UC-ARD32.
    """


def is_mother_project(project_root: Path) -> bool:
    """Return whether ``project_root`` is (or shares a checkout with) Mother."""
    return git_common_root(project_root).resolve() == git_common_root(REPO_ROOT).resolve()


def reach_ok(project_root: Path, source: ArtifactSource) -> bool:
    """Return whether ``project_root`` may publish ``source``."""
    if source.reach is ArtifactReach.SELF:
        return True
    if source.reach is ArtifactReach.MOTHER_ONLY:
        return is_mother_project(project_root)
    return source.domain in publishes_for_root(project_root)


def reach_violation(project_root: Path, source: ArtifactSource) -> str | None:
    """Return a human-readable reach-violation message, or ``None`` when in reach."""
    if reach_ok(project_root, source):
        return None
    if source.reach is ArtifactReach.MOTHER_ONLY:
        return f"{source.entrypoint} is a Mother-only agent-artifact source; this project may not publish it"
    return (
        f"{source.entrypoint} publishes global domain '{source.domain}', "
        f"which this project does not declare in business.publishes"
    )


def _agents_root(project_root: Path) -> Path:
    return project_root / AGENT_ARTIFACT_ROOT_DIRNAME


def local_tier_root(project_root: Path) -> Path:
    """Return a repository's local agent-artifact tier root, ``agents/local``."""
    return _agents_root(project_root) / _LOCAL_DIRNAME


def project_commands_root(project_root: Path) -> Path:
    """Return the project-tier command source root the registry classifies.

    The single owner of this path: a consumer that needs "where do this
    project's own commands live" asks here rather than re-deriving the
    ``agents/local/commands`` join itself.
    """
    return _agents_root(project_root) / _LOCAL_DIRNAME / _COMMANDS_DIRNAME


def command_source_roots(project_root: Path) -> tuple[Path, Path]:
    """Return the global and project command roots owned by this registry."""
    agents_root = _agents_root(project_root)
    return agents_root / _GLOBAL_DIRNAME / _COMMANDS_DIRNAME, project_commands_root(project_root)


def _global_command_directories(project_root: Path) -> Iterator[Path]:
    global_root, _ = command_source_roots(project_root)
    if global_root.is_dir():
        yield from sorted((entry for entry in global_root.iterdir() if entry.is_dir()), key=lambda path: path.name)


def retirement_command_companions(project_root: Path) -> list[CommandRetirementCompanion]:
    """List valid retirement companions beside classified global and project commands."""
    roots = [*_global_command_directories(project_root), project_commands_root(project_root)]
    companions: list[CommandRetirementCompanion] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir(), key=lambda entry: entry.name):
            shape = companion_shape(path)
            if not path.is_file() or shape is None or not is_retirement_companion(path):
                continue
            stem, slug = shape
            companions.append(
                CommandRetirementCompanion(
                    companion_path=path,
                    command_path=root / (stem + _MARKDOWN_SUFFIX),
                    slug=slug,
                )
            )
    return companions


def project_skills_root(project_root: Path) -> Path:
    """Return the project-tier skill source root the registry classifies."""
    return _agents_root(project_root) / _LOCAL_DIRNAME / _SKILLS_DIRNAME


def _iter_root_files(project_root: Path) -> Iterator[ArtifactSource]:
    project_master = project_root / _PROJECT_MASTER_FILENAME
    if project_master.is_file():
        yield ArtifactSource(
            entrypoint=project_master,
            tier=ArtifactTier.ROOT,
            authorship=ArtifactAuthorship.AUTHORED,
            reach=ArtifactReach.SELF,
        )
    agents_root = _agents_root(project_root)
    global_master = agents_root / _GLOBAL_MASTER_FILENAME
    if global_master.is_file():
        yield ArtifactSource(
            entrypoint=global_master,
            tier=ArtifactTier.ROOT,
            authorship=ArtifactAuthorship.AUTHORED,
            reach=ArtifactReach.MOTHER_ONLY,
        )
    global_baseline = agents_root / _GLOBAL_BASELINE_FILENAME
    if global_baseline.is_file():
        yield ArtifactSource(
            entrypoint=global_baseline,
            tier=ArtifactTier.ROOT,
            authorship=ArtifactAuthorship.AUTHORED,
            reach=ArtifactReach.MOTHER_ONLY,
        )
    if agents_root.is_dir():
        for entry in sorted(agents_root.iterdir(), key=lambda path: path.name):
            if entry.is_file() and entry.name.endswith(_ADDENDUM_SUFFIX):
                yield ArtifactSource(
                    entrypoint=entry,
                    tier=ArtifactTier.ROOT,
                    authorship=ArtifactAuthorship.AUTHORED,
                    reach=ArtifactReach.MOTHER_ONLY,
                )


def _iter_uniform_command_tree(
    root: Path, *, tier: ArtifactTier, reach: ArtifactReach, domain: str | None
) -> Iterator[ArtifactSource]:
    """Enumerate command sources, excluding dotted companion-shaped siblings."""
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if entry.is_file() and entry.suffix == _MARKDOWN_SUFFIX and companion_shape(entry) is None:
            yield ArtifactSource(
                entrypoint=entry,
                tier=tier,
                authorship=ArtifactAuthorship.AUTHORED,
                reach=reach,
                kind=ArtifactKind.COMMAND,
                domain=domain,
            )


def _iter_skill_packages(
    root: Path, *, tier: ArtifactTier, reach: ArtifactReach, authorship: ArtifactAuthorship
) -> Iterator[ArtifactSource]:
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir():
            continue
        skill_entrypoint = entry / _SKILL_ENTRYPOINT_FILENAME
        if skill_entrypoint.is_file():
            yield ArtifactSource(
                entrypoint=skill_entrypoint,
                tier=tier,
                authorship=authorship,
                reach=reach,
                kind=ArtifactKind.SKILL,
            )


def _iter_skill_package_tree(
    root: Path,
    catalog_master_name: str,
    *,
    tier: ArtifactTier,
    reach: ArtifactReach,
    authorship: ArtifactAuthorship,
) -> Iterator[ArtifactSource]:
    if not root.is_dir():
        return
    catalog_master = root / catalog_master_name
    if catalog_master.is_file():
        yield ArtifactSource(
            entrypoint=catalog_master,
            tier=tier,
            authorship=ArtifactAuthorship.AUTHORED,
            reach=reach,
        )
    yield from _iter_skill_packages(root, tier=tier, reach=reach, authorship=authorship)


def _iter_global_commands(project_root: Path) -> Iterator[ArtifactSource]:
    for domain_dir in _global_command_directories(project_root):
        yield from _iter_uniform_command_tree(
            domain_dir, tier=ArtifactTier.GLOBAL, reach=ArtifactReach.DOMAIN, domain=domain_dir.name
        )


def _iter_global_skills(project_root: Path) -> Iterator[ArtifactSource]:
    agents_root = _agents_root(project_root)
    yield from _iter_skill_package_tree(
        agents_root / _GLOBAL_DIRNAME / _SKILLS_DIRNAME,
        _GLOBAL_MASTER_FILENAME,
        tier=ArtifactTier.GLOBAL,
        reach=ArtifactReach.MOTHER_ONLY,
        authorship=ArtifactAuthorship.INCORPORATED,
    )


def _iter_project_sources(project_root: Path) -> Iterator[ArtifactSource]:
    yield from _iter_uniform_command_tree(
        project_commands_root(project_root),
        tier=ArtifactTier.PROJECT,
        reach=ArtifactReach.SELF,
        domain=None,
    )
    yield from _iter_skill_packages(
        project_skills_root(project_root),
        tier=ArtifactTier.PROJECT,
        reach=ArtifactReach.SELF,
        authorship=ArtifactAuthorship.AUTHORED,
    )


def all_sources(project_root: Path) -> list[ArtifactSource]:
    """Enumerate every classified agent-artifact source this project carries.

    Every source path matches exactly one record here; there is no overlap
    between the root, global, and project trees, and ``.agents/`` is never
    walked. Callers needing only commands or only skills filter on ``kind``.
    """
    root = project_root.resolve()
    sources: list[ArtifactSource] = []
    sources.extend(_iter_root_files(root))
    sources.extend(_iter_global_commands(root))
    sources.extend(_iter_global_skills(root))
    sources.extend(_iter_project_sources(root))
    return sources


def _boundary_violation(project_root: Path, resolved: Path) -> str | None:
    """Return a message when ``resolved`` sits inside ``agents/`` but names no
    recognized tier-kind boundary, or ``None`` when it is outside ``agents/``
    entirely (not a source, not a violation) or inside a recognized one
    (classified elsewhere, or a stray file one level under an otherwise-valid
    tree — out of this boundary check's scope).
    """
    agents_root = _agents_root(project_root).resolve()
    try:
        relative_parts = resolved.relative_to(agents_root).parts
    except ValueError:
        return None
    if not relative_parts:
        return None
    first = relative_parts[0]
    if first.endswith(_ADDENDUM_SUFFIX) or first in (
        _GLOBAL_MASTER_FILENAME,
        _GLOBAL_BASELINE_FILENAME,
        _GENERATED_ROOT_ENTRYPOINT_FILENAME,
    ):
        return None
    if first in (_GLOBAL_DIRNAME, _LOCAL_DIRNAME):
        if len(relative_parts) < 2 or relative_parts[1] in (_COMMANDS_DIRNAME, _SKILLS_DIRNAME):
            return None
        return (
            f"{resolved} is under agents/{first}/, which admits only "
            f"'{_COMMANDS_DIRNAME}' and '{_SKILLS_DIRNAME}' as agent-artifact kinds"
        )
    return f"{resolved} is directly under agents/ but is not a recognized master, addendum, or tier root"


def classify_candidate(project_root: Path, candidate: Path) -> ArtifactSource | None:
    """Classify one concrete path against ``project_root``'s declared sources.

    Returns the matching :class:`ArtifactSource` when ``candidate`` is (or is
    contained by) a classified source's entrypoint unit — a command file, a
    skill package directory, or a root master/addendum file — and ``None``
    when it is not an agent-artifact source at all (including anything under
    ``.agents/``). Raises :class:`UnclassifiedSourceError` when ``candidate``
    sits inside ``agents/`` but matches no recognized tier-kind boundary — an
    unrecognized kind directory or a stray top-level entry — rather than
    silently treating it as absent.
    """
    root = project_root.resolve()
    resolved = candidate if candidate.is_absolute() else root / candidate
    resolved = resolved.resolve(strict=False)
    shape = companion_shape(resolved)
    if shape is not None and resolved.parent in (
        project_commands_root(root),
        *_global_command_directories(root),
    ):
        source_path = resolved.parent / (shape[0] + _MARKDOWN_SUFFIX)
        source = next(
            (
                item
                for item in all_sources(root)
                if item.kind is ArtifactKind.COMMAND and item.entrypoint.resolve(strict=False) == source_path
            ),
            None,
        )
        if source is not None and is_retirement_companion(resolved):
            return source
        raise UnclassifiedSourceError(_MALFORMED_COMMAND_SOURCE_TEMPLATE.format(path=resolved))
    for source in all_sources(root):
        entrypoint = source.entrypoint.resolve(strict=False)
        if source.kind is ArtifactKind.SKILL:
            if resolved == entrypoint or entrypoint.parent in resolved.parents or resolved == entrypoint.parent:
                return source
            continue
        if resolved == entrypoint:
            return source
    violation = _boundary_violation(root, resolved)
    if violation is not None:
        raise UnclassifiedSourceError(violation)
    return None


def boundary_violations(project_root: Path) -> list[str]:
    """Return a violation message for every unrecognized, non-ignored entry under ``agents/``.

    A repo-wide scan has no candidate path to probe with :func:`classify_candidate`,
    so an unrecognized kind directory (``agents/global/unknown-kind/``, for
    example) would otherwise never be discovered — nothing enumerates it as a
    source in the first place. This walks the fixed boundary levels the tiered
    layout defines (``agents/``, ``agents/global/``, ``agents/local/``)
    directly, skipping entries Git ignores so a full scan sees repository
    boundary violations rather than local filesystem noise.
    """
    root = project_root.resolve()
    agents_root = _agents_root(root)
    if not agents_root.is_dir():
        return []
    violations: list[str] = []
    boundary_entries = list(sorted(agents_root.iterdir(), key=lambda path: path.name))
    for tier_name in (_GLOBAL_DIRNAME, _LOCAL_DIRNAME):
        tier_root = agents_root / tier_name
        if not tier_root.is_dir():
            continue
        boundary_entries.extend(sorted(tier_root.iterdir(), key=lambda path: path.name))
    relative_entries = [entry.relative_to(root).as_posix() for entry in boundary_entries]
    if relative_entries:
        with TemporaryFile() as ignore_input:
            ignore_input.write(b"\0".join(os.fsencode(path) for path in relative_entries))
            ignore_input.seek(0)
            try:
                ignored_entries = set(
                    Repo(root).git.check_ignore(*_GIT_CHECK_IGNORE_ARGUMENTS, istream=ignore_input).split("\0")
                )
            except GitCommandError as error:
                if error.status == _GIT_CHECK_IGNORE_NOT_IGNORED_STATUS:
                    ignored_entries = set()
                else:
                    return [_GIT_IGNORE_QUERY_FAILURE_TEMPLATE.format(error=error)]
            except (InvalidGitRepositoryError, NoSuchPathError, OSError) as error:
                return [_GIT_IGNORE_QUERY_FAILURE_TEMPLATE.format(error=error)]
    else:
        ignored_entries = set()
    for entry, relative_entry in zip(boundary_entries, relative_entries):
        if relative_entry in ignored_entries:
            continue
        violation = _boundary_violation(root, entry.resolve(strict=False))
        if violation is not None:
            violations.append(violation)
    command_directories = [*_global_command_directories(root), project_commands_root(root)]
    for command_root in command_directories:
        if not command_root.is_dir():
            continue
        for entry in sorted(command_root.iterdir(), key=lambda path: path.name):
            if entry.is_file() and entry.suffix == _MARKDOWN_SUFFIX and companion_shape(entry) is not None:
                if not is_retirement_companion(entry):
                    violations.append(_MALFORMED_COMMAND_SOURCE_TEMPLATE.format(path=entry))
    return violations

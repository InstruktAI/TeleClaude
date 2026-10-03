"""Quality-check families and candidate grading-root selection."""

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from teleclaude.capabilities import (
    Capabilities,
    PermissionSurface,
    TierPermissions,
    resolve_tier_permissions,
)
from teleclaude.config.context_root import group_paths_by_owning_home, resolve_context_root
from teleclaude.git_tree import TreeSource, list_tree_paths
from teleclaude.paths import ConfigFileName

_ROOT_RELATIVE_PATH = Path(".")


class GradingRoot(NamedTuple):
    """A repository-relative root whose tier grades candidate paths."""

    root: Path

    def relative_path(self, repository_path: str | Path) -> str:
        """Return a candidate path in this grading root's coordinates."""
        return Path(repository_path).relative_to(self.root).as_posix()


def resolve_repository_grading_root(repository_root: Path, source: TreeSource) -> GradingRoot | None:
    """Resolve the candidate root declaration or the readable repository context."""
    tree_paths = set(list_tree_paths(source))
    if ConfigFileName.OVERLAY.value in tree_paths:
        group_paths_by_owning_home([ConfigFileName.OVERLAY.value], source, tree_paths=tree_paths)
        return GradingRoot(root=_ROOT_RELATIVE_PATH)

    context = resolve_context_root(repository_root)
    if context is None or context.path != repository_root.resolve():
        return None
    return GradingRoot(root=_ROOT_RELATIVE_PATH)


def group_paths_by_grading_root(
    relative_paths: Iterable[str | Path],
    source: TreeSource,
    grading_root: GradingRoot,
) -> dict[GradingRoot, list[str]]:
    """Partition candidates by committed-tree owner, falling back to the repository root."""
    paths = [path.as_posix() if isinstance(path, Path) else path for path in relative_paths]
    tree_paths = set(list_tree_paths(source))
    owned_paths = group_paths_by_owning_home(paths, source, tree_paths=tree_paths)
    grouped: dict[GradingRoot, list[str]] = {
        GradingRoot(root=owner.root): paths for owner, paths in owned_paths.items()
    }
    owned = {path for paths in owned_paths.values() for path in paths}
    ownerless_paths = [path for path in paths if path not in owned]
    if ownerless_paths:
        grouped.setdefault(grading_root, []).extend(ownerless_paths)
    return grouped


class QualityCheckFamily(StrEnum):
    """Capability families selected inside TeleClaude's guardrails lane."""

    CODE = "code"
    DOCUMENTATION = "docs"
    AGENTS = "agents"


class QualityGateLeg(StrEnum):
    """Independently selectable quality checks for a sealed commit."""

    NATIVE = "native"
    GUARDRAILS = "guardrails"


class GradingHomeSelection(NamedTuple):
    """One grading home's repository root, paths, and selected quality work."""

    grading_root: GradingRoot
    root: Path
    paths: tuple[str, ...]
    legs: frozenset[QualityGateLeg]
    families: frozenset[QualityCheckFamily]


def select_quality_check_families(
    capabilities: Capabilities,
    tier_permissions: TierPermissions | None,
) -> frozenset[QualityCheckFamily]:
    """Resolve the check families carried by one configured home."""
    if not capabilities.is_target:
        if tier_permissions is None or not tier_permissions.participates_in(PermissionSurface.DOCUMENTATION):
            return frozenset()
        return frozenset({QualityCheckFamily.DOCUMENTATION, QualityCheckFamily.AGENTS})
    selected: set[QualityCheckFamily] = set()
    if capabilities.code:
        selected.add(QualityCheckFamily.CODE)
    if capabilities.docs:
        selected.add(QualityCheckFamily.DOCUMENTATION)
    if capabilities.agents:
        selected.add(QualityCheckFamily.AGENTS)
    return frozenset(selected)


def select_quality_gate_legs(
    capabilities: Capabilities,
    tier_permissions: TierPermissions | None,
) -> frozenset[QualityGateLeg]:
    """Return the gate legs selected by a tier's published capabilities."""
    families = select_quality_check_families(capabilities, tier_permissions)
    if not families or (capabilities.is_target and not capabilities.commit_enabled):
        return frozenset()
    legs = {QualityGateLeg.GUARDRAILS}
    if QualityCheckFamily.CODE in families:
        legs.add(QualityGateLeg.NATIVE)
    return frozenset(legs)


def select_grading_homes(
    repository_root: Path,
    relative_paths: Iterable[str | Path],
    source: TreeSource,
    grading_root: GradingRoot,
) -> tuple[GradingHomeSelection, ...]:
    """Select each candidate home's quality legs and check families."""
    grouped_paths = group_paths_by_grading_root(relative_paths, source, grading_root)
    selections: list[GradingHomeSelection] = []
    for home_grading_root, paths in sorted(grouped_paths.items(), key=lambda item: item[0].root.as_posix()):
        home_paths = tuple(sorted(set(paths)))
        if not home_paths:
            continue
        home_root = (repository_root / home_grading_root.root).resolve()
        permissions = resolve_tier_permissions(home_root)
        families = select_quality_check_families(permissions.project_subscriptions, permissions)
        legs = select_quality_gate_legs(permissions.project_subscriptions, permissions)
        selections.append(GradingHomeSelection(home_grading_root, home_root, home_paths, legs, families))
    return tuple(selections)


__all__ = [
    "GradingHomeSelection",
    "QualityCheckFamily",
    "QualityGateLeg",
    "select_grading_homes",
    "select_quality_check_families",
    "select_quality_gate_legs",
]

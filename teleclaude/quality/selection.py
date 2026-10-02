"""Closed quality-check family vocabulary shared across gate composition."""

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

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
        root_owners = group_paths_by_owning_home([ConfigFileName.OVERLAY.value], source, tree_paths=tree_paths)
        if not root_owners:
            return None
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


__all__ = ["QualityCheckFamily"]

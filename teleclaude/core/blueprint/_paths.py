"""Canonical filesystem locations for the codebase Blueprint cache.

The Blueprint lives at the main project root under ``.teleclaude/blueprint/``,
gitignored and shared across worktrees like ``.teleclaude/todos.db`` — so every worktree
reads the one baseline the integrator generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root

_STATE_DIRNAME = ".teleclaude"
_BLUEPRINT_DIRNAME = "blueprint"
_GENERATIONS_DIRNAME = "generations"
_CURRENT_GENERATION_NAME = "current"
_GRAPHIFY_OUT_DIRNAME = "graphify-out"

GRAPH_FILENAME = "graph.json"
MANIFEST_FILENAME = "manifest.json"
REFRESH_LOCK_FILENAME = "refresh.lock"


@dataclass(frozen=True)
class PinnedBlueprintGeneration:
    """The graph and manifest paths resolved from one current-generation pointer read."""

    directory: Path
    graph: Path
    manifest: Path


def blueprint_dir(start: str | Path) -> Path:
    """Return ``<state-root>/.teleclaude/blueprint`` for a path inside the repo or a worktree."""
    return resolve_project_root(start) / _STATE_DIRNAME / _BLUEPRINT_DIRNAME


def graph_path(start: str | Path) -> Path:
    """Return the Blueprint graph path (``graph.json``)."""
    return blueprint_dir(start) / GRAPH_FILENAME


def manifest_path(start: str | Path) -> Path:
    """Return the Blueprint freshness-manifest path (``manifest.json``)."""
    return blueprint_dir(start) / MANIFEST_FILENAME


def generations_dir(start: str | Path) -> Path:
    """Return the immutable Blueprint generation directory."""
    return blueprint_dir(start) / _GENERATIONS_DIRNAME


def current_generation_pointer(start: str | Path) -> Path:
    """Return the single symlink that selects the published generation."""
    return blueprint_dir(start) / _CURRENT_GENERATION_NAME


def pin_current_generation(start: str | Path) -> PinnedBlueprintGeneration | None:
    """Resolve the published generation pointer once and return its stable file paths."""
    pointer = current_generation_pointer(start)
    if not pointer.is_symlink():
        return None
    try:
        directory = pointer.resolve(strict=True)
        expected_parent = generations_dir(start).resolve()
    except OSError:
        return None
    if not directory.is_dir() or directory.parent != expected_parent:
        return None
    return PinnedBlueprintGeneration(
        directory=directory,
        graph=directory / GRAPH_FILENAME,
        manifest=directory / MANIFEST_FILENAME,
    )


def graphify_graph_path(start: str | Path) -> Path:
    """Return Graphify's standard graph output path, retained as a published alias."""
    return Path(start).expanduser().resolve() / _GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME


def refresh_lock_path(start: str | Path) -> Path:
    """Return the single-flight lock path for a detached Blueprint refresh."""
    return blueprint_dir(start) / REFRESH_LOCK_FILENAME

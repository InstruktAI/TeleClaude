"""Canonical filesystem locations for the codebase Blueprint cache.

The Blueprint lives at the main project root under ``.teleclaude/blueprint/``,
gitignored and shared across worktrees like ``.teleclaude/todos.db`` — so every worktree
reads the one baseline the integrator generated.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.project_root import resolve_state_root

_STATE_DIRNAME = ".teleclaude"
_BLUEPRINT_DIRNAME = "blueprint"

GRAPH_FILENAME = "graph.json"
MANIFEST_FILENAME = "manifest.json"


def blueprint_dir(start: str | Path) -> Path:
    """Return ``<state-root>/.teleclaude/blueprint`` for a path inside the repo or a worktree."""
    return resolve_state_root(start) / _STATE_DIRNAME / _BLUEPRINT_DIRNAME


def graph_path(start: str | Path) -> Path:
    """Return the Blueprint graph path (``graph.json``)."""
    return blueprint_dir(start) / GRAPH_FILENAME


def manifest_path(start: str | Path) -> Path:
    """Return the Blueprint freshness-manifest path (``manifest.json``)."""
    return blueprint_dir(start) / MANIFEST_FILENAME

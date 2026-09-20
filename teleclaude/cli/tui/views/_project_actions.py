"""Shared helpers for project-related view actions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from teleclaude.config.machine_config_mutation import add_trusted_directory


class NewProjectResultLike(Protocol):
    """Duck-typed project modal result used by the view helpers."""

    name: str
    path: str
    description: str | None


class ProjectNotifier(Protocol):
    """Minimal notification protocol needed by project action helpers."""

    def notify(self, message: str, *, severity: str = "information") -> None:
        """Notify the user of a project action result."""

    def notify_text(self, message: str, *, severity: str = "information") -> None:
        """Notify the user with text the caller did not author, rendered as data."""


def _normalize_project_path(raw_path: str) -> Path:
    """Normalize user input into a stable absolute path."""
    return Path(os.path.expandvars(raw_path)).expanduser().resolve(strict=False)


def _ensure_project_directory(raw_path: str) -> tuple[Path, bool]:
    """Ensure the project path exists as a directory."""
    project_path = _normalize_project_path(raw_path)
    if project_path.exists():
        if not project_path.is_dir():
            raise ValueError(f"Path exists and is not a directory: {project_path}")
        return project_path, False

    project_path.mkdir(parents=True, exist_ok=True)
    return project_path, True


def _rollback_created_directory(project_path: Path | None, created_project_dir: bool) -> None:
    """Best-effort cleanup for a freshly created empty project directory."""
    if not created_project_dir or project_path is None:
        return
    try:
        project_path.rmdir()
    except OSError:
        pass


def save_new_project(app: ProjectNotifier, result: NewProjectResultLike) -> bool:
    """Persist a new trusted project and notify the user about the outcome."""
    project_path: Path | None = None
    created_project_dir = False
    try:
        project_path, created_project_dir = _ensure_project_directory(result.path)
        add_trusted_directory(result.name, str(project_path), result.description or "")
    except Exception as exc:
        _rollback_created_directory(project_path, created_project_dir)
        app.notify_text(f"Failed to save project: {str(exc)[:80]}", severity="error")
        return False

    app.notify_text(f"Project '{result.name}' added")
    return True

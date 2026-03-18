"""Shared helpers for project-related view actions."""

from __future__ import annotations

import subprocess
from typing import Protocol

from textual.app import App


class NewProjectResultLike(Protocol):  # pylint: disable=too-few-public-methods
    """Duck-typed project modal result used by the view helpers."""

    name: str
    path: str
    description: str | None


def save_new_project(app: App, result: NewProjectResultLike) -> bool:
    """Persist a new trusted project and notify the user about the outcome."""
    yaml_patch = f"computer:\n  trusted_dirs:\n    - name: {result.name}\n      path: {result.path}\n"
    if result.description:
        yaml_patch += f"      description: {result.description}\n"

    try:
        subprocess.run(
            ["telec", "config", "patch", "--yaml", yaml_patch],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="ignore") if exc.stderr else str(exc)
        app.notify(f"Failed to save project: {stderr[:80]}", severity="error")
        return False

    app.notify(f"Project '{result.name}' added")
    return True

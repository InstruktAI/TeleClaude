"""Helpers for logical todo artifact names and persistence delegation."""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.workflow_store import write_workflow_artifact_sync


def artifact_display_filename(artifact_name: str) -> str:
    """Return the user-facing artifact name without inventing a file extension."""
    return artifact_name


def write_artifact_content(project_root: Path, slug: str, artifact_name: str, content: str) -> None:
    """Write a workflow artifact through the selected store."""
    write_workflow_artifact_sync(project_root, slug, artifact_name, content)

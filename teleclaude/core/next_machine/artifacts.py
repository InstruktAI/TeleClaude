"""Leaf artifact helpers — no imports from state_io to avoid circular dependency."""

from __future__ import annotations

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_REQUIREMENTS,
)


def compute_artifact_diff(cwd: str, slug: str, artifact_name: str, base_sha: str) -> str:
    """No filesystem file to diff — artifacts live in todos.db."""
    return ""


def compute_todo_folder_diff(cwd: str, slug: str, base_sha: str) -> str:
    """No filesystem folder to diff — artifacts live in todos.db."""
    return ""


def artifact_name_to_state_key(artifact_name: str) -> str:
    """Map a DB artifact name to its state dict key."""
    mapping = {
        ARTIFACT_INPUT: "input",
        ARTIFACT_REQUIREMENTS: "requirements",
        ARTIFACT_IMPLEMENTATION_PLAN: "implementation_plan",
    }
    return mapping.get(artifact_name, artifact_name.replace(".", "_").replace("-", "_"))

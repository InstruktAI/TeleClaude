"""Leaf artifact helpers shared across prepare and state modules."""

# pylint: disable=duplicate-code,cyclic-import  # Backward-compat helpers mirror prepare_helpers; state_io cycle is legacy.

from __future__ import annotations

from datetime import UTC, datetime

from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.state_io import _get_todos_db_sync, read_phase_state, write_phase_state


def artifact_digest(cwd: str, slug: str, artifact_name: str) -> str:
    """Read artifact digest from todos.db."""
    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT digest FROM todo_artifacts WHERE slug = ? AND name = ? LIMIT 1",  # guard: raw-sql
            (slug, artifact_name),
        ).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def record_artifact_produced(cwd: str, slug: str, artifact_name: str) -> None:
    """Record artifact production metadata in state.yaml."""
    key = _artifact_name_to_state_key(artifact_name)
    digest = artifact_digest(cwd, slug, artifact_name)
    now = datetime.now(UTC).isoformat()

    state = read_phase_state(cwd, slug)
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    entry = artifacts.get(key, {})
    if not isinstance(entry, dict):
        entry = {}
    entry["digest"] = digest
    entry["produced_at"] = now
    entry["stale"] = False
    artifacts[key] = entry
    state["artifacts"] = artifacts
    write_phase_state(cwd, slug, state)

    _emit_prepare_event(
        "domain.software-development.prepare.artifact_produced",
        {"slug": slug, "artifact": artifact_name, "digest": digest},
    )


def compute_artifact_diff(cwd: str, slug: str, artifact_name: str, base_sha: str) -> str:  # pylint: disable=unused-argument
    """No filesystem file to diff — artifacts live in todos.db."""
    return ""


def compute_todo_folder_diff(cwd: str, slug: str, base_sha: str) -> str:  # pylint: disable=unused-argument
    """No filesystem folder to diff — artifacts live in todos.db."""
    return ""


def _artifact_name_to_state_key(artifact_name: str) -> str:
    """Map a DB artifact name to its state dict key."""
    mapping = {
        "input": "input",
        "requirements": "requirements",
        "implementation-plan": "implementation_plan",
    }
    return mapping.get(artifact_name, artifact_name.replace(".", "_").replace("-", "_"))

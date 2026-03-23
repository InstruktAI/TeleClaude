"""Leaf artifact helpers shared across prepare and state modules."""
# pylint: disable=duplicate-code  # compute_artifact_diff/compute_todo_folder_diff also exist in prepare_helpers for backward compat

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from teleclaude.core.next_machine.file_io import file_sha256
from teleclaude.core.next_machine.git_ops import run_git_command
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state


def artifact_digest(cwd: str, slug: str, artifact_name: str) -> str:
    """Compute SHA-256 digest of todos/{slug}/{artifact_name}."""
    path = Path(cwd) / "todos" / slug / artifact_name
    if not path.exists():
        return ""
    return file_sha256(path)


def record_artifact_produced(cwd: str, slug: str, artifact_name: str) -> None:
    """Record artifact production metadata in state.yaml."""
    key = _filename_to_artifact_key(artifact_name)
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


def compute_artifact_diff(cwd: str, slug: str, artifact_path: str, base_sha: str) -> str:  # pylint: disable=unused-argument
    """Run git diff {base_sha}..HEAD -- {artifact_path} and return the diff output."""
    if not base_sha:
        return ""
    rc, stdout, _ = run_git_command(["diff", f"{base_sha}..HEAD", "--", artifact_path], cwd=cwd)
    if rc != 0:
        return ""
    return stdout


def compute_todo_folder_diff(cwd: str, slug: str, base_sha: str) -> str:
    """Run git diff {base_sha}..HEAD -- todos/{slug}/ and return the diff output."""
    if not base_sha:
        return ""
    rc, stdout, _ = run_git_command(["diff", f"{base_sha}..HEAD", "--", f"todos/{slug}/"], cwd=cwd)
    if rc != 0:
        return ""
    return stdout


def _filename_to_artifact_key(filename: str) -> str:
    mapping = {
        "input.md": "input",
        "requirements.md": "requirements",
        "implementation-plan.md": "implementation_plan",
    }
    return mapping.get(filename, filename.replace(".", "_").replace("-", "_"))

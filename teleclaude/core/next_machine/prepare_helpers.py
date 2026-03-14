"""Shared helpers for prepare-phase artifact lifecycle bookkeeping.

Workers call these after producing or consuming artifacts. The machine invokes
staleness checks on each prepare invocation. All state mutations go through
read_phase_state/write_phase_state for atomicity.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state

logger = logging.getLogger(__name__)

# Canonical cascade order for staleness detection
_ARTIFACT_CASCADE: list[tuple[str, str]] = [
    ("input", "input.md"),
    ("requirements", "requirements.md"),
    ("implementation_plan", "implementation-plan.md"),
]


def artifact_digest(cwd: str, slug: str, artifact_name: str) -> str:
    """Compute SHA-256 digest of todos/{slug}/{artifact_name}.

    Returns hex digest string, or empty string if file does not exist.
    """
    path = Path(cwd) / "todos" / slug / artifact_name
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_artifact_produced(cwd: str, slug: str, artifact_name: str) -> None:
    """Record that an artifact was produced: writes digest and produced_at to state.yaml.

    Maps artifact filenames to state keys:
    - input.md → artifacts.input
    - requirements.md → artifacts.requirements
    - implementation-plan.md → artifacts.implementation_plan
    """
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


def check_artifact_staleness(cwd: str, slug: str) -> list[str]:
    """Check each tracked artifact for staleness by comparing current digest to stored digest.

    Returns list of stale artifact keys (state key names like 'input', 'requirements',
    'implementation_plan') starting from the earliest changed one. All downstream
    artifacts are included when any upstream artifact changes.
    """
    state = read_phase_state(cwd, slug)
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return []

    stale_from: int | None = None
    for idx, (key, filename) in enumerate(_ARTIFACT_CASCADE):
        entry = artifacts.get(key, {})
        if not isinstance(entry, dict):
            continue
        stored_digest = str(entry.get("digest", ""))
        if not stored_digest:
            # Not yet recorded — not stale (no baseline to compare against)
            continue
        current = artifact_digest(cwd, slug, filename)
        if current != stored_digest:
            stale_from = idx
            break

    if stale_from is None:
        return []

    return [key for key, _ in _ARTIFACT_CASCADE[stale_from:]]


def record_finding(cwd: str, slug: str, review_type: str, finding: dict[str, StateValue]) -> None:
    """Append a structured finding to the review's findings list in state.yaml."""
    state = read_phase_state(cwd, slug)
    review = state.get(review_type, {})
    if not isinstance(review, dict):
        review = {}
    findings: list[object] = list(review.get("findings", []) or [])  # type: ignore[arg-type]
    findings.append(finding)
    review["findings"] = findings  # type: ignore[assignment]
    state[review_type] = review
    write_phase_state(cwd, slug, state)

    _emit_prepare_event(
        "domain.software-development.prepare.finding_recorded",
        {
            "slug": slug,
            "review_type": review_type,
            "severity": finding.get("severity", ""),  # type: ignore[dict-item]
            "summary": finding.get("summary", ""),  # type: ignore[dict-item]
        },
    )


def resolve_finding(cwd: str, slug: str, review_type: str, finding_id: str, resolution_method: str) -> None:
    """Mark a finding as resolved in state.yaml."""
    now = datetime.now(UTC).isoformat()
    state = read_phase_state(cwd, slug)
    review = state.get(review_type, {})
    if not isinstance(review, dict):
        review = {}
    findings: list[object] = list(review.get("findings", []) or [])  # type: ignore[arg-type]
    matched = False
    for f in findings:
        if isinstance(f, dict) and f.get("id") == finding_id:
            f["status"] = "resolved"
            f["resolved_at"] = now
            matched = True
    if not matched:
        logger.warning("resolve_finding: finding_id=%s not found in %s/%s", finding_id, slug, review_type)
        return
    review["findings"] = findings  # type: ignore[assignment]
    state[review_type] = review
    write_phase_state(cwd, slug, state)

    _emit_prepare_event(
        "domain.software-development.prepare.finding_resolved",
        {"slug": slug, "review_type": review_type, "finding_id": finding_id, "resolution_method": resolution_method},
    )


def stamp_audit(state: dict[str, StateValue], phase_name: str, field: str, value: StateValue) -> None:
    """Safely navigate the nested audit dict and write a field value in-place."""
    audit = state.get("audit")
    if not isinstance(audit, dict):
        audit = {}
        state["audit"] = audit
    phase_entry = audit.get(phase_name)
    if not isinstance(phase_entry, dict):
        phase_entry = {}
        audit[phase_name] = phase_entry
    phase_entry[field] = value


def compute_artifact_diff(cwd: str, slug: str, artifact_path: str, base_sha: str) -> str:
    """Run git diff {base_sha}..HEAD -- {artifact_path} and return the diff output.

    Returns empty string if base_sha is empty or if the diff produces no output.
    """
    if not base_sha:
        return ""
    rc, stdout, _ = _run_git_prepare(["diff", f"{base_sha}..HEAD", "--", artifact_path], cwd=cwd)
    if rc != 0:
        return ""
    return stdout


def compute_todo_folder_diff(cwd: str, slug: str, base_sha: str) -> str:
    """Run git diff {base_sha}..HEAD -- todos/{slug}/ and return the diff output."""
    if not base_sha:
        return ""
    rc, stdout, _ = _run_git_prepare(["diff", f"{base_sha}..HEAD", "--", f"todos/{slug}/"], cwd=cwd)
    if rc != 0:
        return ""
    return stdout


def record_input_consumed(cwd: str, slug: str) -> None:
    """Emit prepare.input_consumed event with current input.md digest.

    Pure observation event — does not modify state.yaml.
    """
    digest = artifact_digest(cwd, slug, "input.md")
    _emit_prepare_event(
        "domain.software-development.prepare.input_consumed",
        {"slug": slug, "phase": "input_assessment", "digest": digest},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _filename_to_artifact_key(filename: str) -> str:
    """Map artifact filename to state.artifacts key."""
    mapping = {
        "input.md": "input",
        "requirements.md": "requirements",
        "implementation-plan.md": "implementation_plan",
    }
    return mapping.get(filename, filename.replace(".", "_").replace("-", "_"))


def _run_git_prepare(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("git %s failed (rc=%d): %s", " ".join(args), result.returncode, result.stderr.strip())
    return result.returncode, result.stdout, result.stderr

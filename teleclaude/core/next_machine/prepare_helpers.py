"""Shared helpers for prepare-phase artifact lifecycle bookkeeping.

Workers call these after producing or consuming artifacts. The machine invokes
staleness checks on each prepare invocation. All state mutations go through
read_phase_state/write_phase_state for atomicity.
"""
# pylint: disable=duplicate-code  # compute_artifact_diff/compute_todo_folder_diff are intentionally mirrored in artifacts.py

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.artifacts import (
    artifact_digest,
)
from teleclaude.core.next_machine.git_ops import run_git_command
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

# Canonical cascade order for staleness detection
_ARTIFACT_CASCADE: list[tuple[str, str]] = [
    ("input", "input.md"),
    ("requirements", "requirements.md"),
    ("implementation_plan", "implementation-plan.md"),
]


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
# DB-backed variants (todos.db)
# ---------------------------------------------------------------------------


async def check_artifact_staleness_db(todos_db: TodosDb, slug: str) -> list[str]:
    """DB-backed artifact staleness check.

    Compares stored digests in todo_state.artifacts against current
    digests in todo_artifacts table.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return []
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
            continue
        # DB artifact name is the filename without .md extension (e.g. "implementation-plan")
        db_name = filename.removesuffix(".md") if filename.endswith(".md") else key
        current = await todos_db.artifact_digest(slug, db_name)
        if current != stored_digest:
            stale_from = idx
            break

    if stale_from is None:
        return []

    return [key for key, _ in _ARTIFACT_CASCADE[stale_from:]]

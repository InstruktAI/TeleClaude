# guard: no-companion
"""Unit tests for the validated state mutation boundary.

Covers the four concerns from Task 1 of the state-machine-abstraction plan:
1. `TodoState` accepts the aligned schema (`changed_paths`, typed findings,
   test-spec audit entries).
2. `StateWriter` validates the full state shape and persists exactly once per
   commit via the async and sync DB paths.
3. `GroundingManager.check(...)` returns a stale result when referenced paths
   diverge from the stored baseline, and refresh advances `base_sha`.
4. `ReviewManager.record_finding(...)` rejects duplicate IDs and
   `resolve_finding(...)` rejects unknown IDs.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.state_mutation import (
    GroundingManager,
    ReviewManager,
    StateMutationError,
    StateWriter,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import (
    AuditReviewEntry,
    AuditState,
    GroundingState,
    ReviewFinding,
    ReviewVerdictState,
    TodoState,
)

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def _base_state() -> dict[str, StateValue]:
    """Minimal valid state dict accepted by :class:`TodoState`."""
    return {
        "schema_version": 2,
        "current": "requirements_review",
    }


# ---------------------------------------------------------------------------
# Schema alignment
# ---------------------------------------------------------------------------


def test_grounding_state_accepts_changed_paths_field() -> None:
    """`GroundingState` must persist and round-trip `changed_paths`."""
    grounding = GroundingState(changed_paths=["src/app.py", "src/util.py"])
    assert grounding.changed_paths == ["src/app.py", "src/util.py"]

    dumped = grounding.model_dump()
    assert dumped["changed_paths"] == ["src/app.py", "src/util.py"]


def test_review_verdict_state_stores_typed_findings() -> None:
    """`ReviewVerdictState.findings` must coerce dict records into typed models."""
    review = ReviewVerdictState.model_validate(
        {
            "verdict": "needs_work",
            "findings": [
                {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
            ],
        }
    )
    assert len(review.findings) == 1
    finding = review.findings[0]
    assert isinstance(finding, ReviewFinding)
    assert finding.id == "R1-F1"
    assert finding.severity == "critical"
    assert finding.status == "open"


def test_audit_state_exposes_test_spec_phases() -> None:
    """`AuditState` must include the prepare phases the code already audits."""
    audit = AuditState()
    assert hasattr(audit, "test_spec_build")
    assert hasattr(audit, "test_spec_review")
    assert isinstance(audit.test_spec_review, AuditReviewEntry)


# ---------------------------------------------------------------------------
# StateWriter — validation and single-persist contract
# ---------------------------------------------------------------------------


def test_state_writer_rejects_malformed_grounding_state() -> None:
    """Malformed persisted grounding must be rejected fail-fast at load."""
    bad_state = _base_state()
    bad_state["grounding"] = ["not-a-grounding-dict"]

    with pytest.raises(StateMutationError):
        StateWriter(bad_state)


def test_state_writer_rejects_malformed_review_state() -> None:
    """Malformed review sub-state must be rejected at load."""
    bad_state = _base_state()
    bad_state["requirements_review"] = "broken"

    with pytest.raises(StateMutationError):
        StateWriter(bad_state)


def test_state_writer_loads_and_dumps_round_trip() -> None:
    """Loading a valid state and dumping it must preserve the typed shape."""
    state = _base_state()
    state["grounding"] = {"base_sha": "abc123", "referenced_paths": ["src/a.py"]}

    writer = StateWriter(state)
    assert isinstance(writer.state, TodoState)
    assert writer.grounding.base_sha == "abc123"

    dumped = writer.to_dict()
    assert dumped["grounding"]["base_sha"] == "abc123"  # type: ignore[index]
    assert dumped["grounding"]["referenced_paths"] == ["src/a.py"]  # type: ignore[index]


def test_state_writer_review_rejects_unknown_phase() -> None:
    """`writer.review(...)` must fail fast on unknown phase names."""
    writer = StateWriter(_base_state())
    with pytest.raises(StateMutationError):
        writer.review("not_a_review_phase")


def test_state_writer_audit_entry_rejects_non_review_phase() -> None:
    """`writer.audit_entry(...)` must reject non-review audit entries."""
    writer = StateWriter(_base_state())
    with pytest.raises(StateMutationError):
        # `input_assessment` is an AuditTimestamp, not an AuditReviewEntry.
        writer.audit_entry("input_assessment")


@pytest.mark.asyncio
async def test_state_writer_commit_persists_once_via_async_path() -> None:
    """`commit()` must call `write_state` exactly once with the validated payload."""
    writer = StateWriter(_base_state())
    writer.state.phase = "in_progress"

    todos_db = MagicMock(spec=TodosDb)
    todos_db.write_state = AsyncMock()

    payload = await writer.commit(todos_db, "slug-once")

    todos_db.write_state.assert_awaited_once_with("slug-once", payload)
    assert payload["phase"] == "in_progress"


def test_state_writer_commit_sync_persists_once_via_sync_path() -> None:
    """`commit_sync()` must call `write_state_sync` exactly once."""
    writer = StateWriter(_base_state())
    writer.state.phase = "done"

    todos_db = MagicMock(spec=TodosDb)

    payload = writer.commit_sync(todos_db, "slug-sync")

    todos_db.write_state_sync.assert_called_once_with("slug-sync", payload)
    assert payload["phase"] == "done"


# ---------------------------------------------------------------------------
# GroundingManager — freshness lifecycle
# ---------------------------------------------------------------------------


def test_grounding_manager_check_returns_stale_for_changed_reference() -> None:
    """A changed referenced path must produce a stale result with the path listed."""
    state = _base_state()
    state["grounding"] = {
        "base_sha": "oldsha",
        "input_digest": "digest",
        "referenced_paths": ["src/app.py", "src/other.py"],
    }
    writer = StateWriter(state)
    manager = GroundingManager(writer)

    result = manager.check(
        current_sha="newsha",
        current_input_digest="digest",
        changed_files={"src/app.py"},
    )

    assert result.is_stale is True
    assert result.reason == "files_changed"
    assert result.changed_paths == ["src/app.py"]


def test_grounding_manager_check_returns_fresh_for_unrelated_change() -> None:
    """A SHA change that does not touch referenced paths stays fresh."""
    state = _base_state()
    state["grounding"] = {
        "base_sha": "oldsha",
        "input_digest": "digest",
        "referenced_paths": ["src/app.py"],
    }
    writer = StateWriter(state)
    manager = GroundingManager(writer)

    result = manager.check(
        current_sha="newsha",
        current_input_digest="digest",
        changed_files={"docs/unrelated.md"},
    )

    assert result.is_stale is False
    assert not result.changed_paths


def test_grounding_manager_check_returns_stale_for_input_digest_change() -> None:
    """An input-digest change must mark the baseline stale with `input_updated`."""
    state = _base_state()
    state["grounding"] = {
        "base_sha": "abc",
        "input_digest": "old-digest",
        "referenced_paths": [],
    }
    writer = StateWriter(state)
    manager = GroundingManager(writer)

    result = manager.check(current_sha="abc", current_input_digest="new-digest")

    assert result.is_stale is True
    assert result.reason == "input_updated"


def test_grounding_manager_refresh_advances_base_sha() -> None:
    """`refresh()` must point the baseline at the new HEAD and clear invalidation."""
    state = _base_state()
    state["grounding"] = {
        "base_sha": "oldsha",
        "valid": False,
        "invalidated_at": "2026-01-01T00:00:00+00:00",
        "invalidation_reason": "files_changed",
        "changed_paths": ["src/app.py"],
    }
    writer = StateWriter(state)
    manager = GroundingManager(writer)

    manager.refresh(current_sha="newsha")

    assert writer.grounding.base_sha == "newsha"
    assert writer.grounding.valid is True
    assert writer.grounding.invalidated_at == ""
    assert writer.grounding.invalidation_reason == ""
    assert writer.grounding.changed_paths == []


def test_grounding_manager_invalidate_records_reason_and_paths() -> None:
    """`invalidate()` must flip `valid=False` and record the given reason/paths."""
    state = _base_state()
    state["grounding"] = {"base_sha": "abc", "valid": True}
    writer = StateWriter(state)
    manager = GroundingManager(writer)

    manager.invalidate(reason="files_changed", changed_paths=["src/a.py"])

    assert writer.grounding.valid is False
    assert writer.grounding.invalidation_reason == "files_changed"
    assert writer.grounding.changed_paths == ["src/a.py"]


def test_grounding_manager_clear_invalidation_wipes_invalidation_trace() -> None:
    """`clear_invalidation()` must flip `valid=True` and erase invalidation trace."""
    state = _base_state()
    state["grounding"] = {
        "base_sha": "abc",
        "valid": False,
        "invalidated_at": "2026-01-01T00:00:00+00:00",
        "invalidation_reason": "files_changed",
        "changed_paths": ["src/a.py"],
    }
    writer = StateWriter(state)
    manager = GroundingManager(writer)

    manager.clear_invalidation()

    assert writer.grounding.valid is True
    assert writer.grounding.invalidated_at == ""
    assert writer.grounding.invalidation_reason == ""
    assert writer.grounding.changed_paths == []
    # base_sha is preserved — clear_invalidation is an explicit revalidation,
    # not a refresh — so downstream grounding logic can still reason about the
    # pinned baseline.
    assert writer.grounding.base_sha == "abc"


# ---------------------------------------------------------------------------
# ReviewManager — verdict and finding lifecycle
# ---------------------------------------------------------------------------


def test_review_manager_stamp_verdict_updates_review_and_audit() -> None:
    """`stamp_verdict` must set the verdict on both review and audit entries."""
    writer = StateWriter(_base_state())
    manager = ReviewManager(writer)

    manager.stamp_verdict("requirements_review", "approve")

    review = writer.review("requirements_review")
    audit_entry = writer.audit_entry("requirements_review")
    assert review.verdict == "approve"
    assert review.reviewed_at  # non-empty ISO timestamp
    assert audit_entry.verdict == "approve"
    assert audit_entry.completed_at


def test_review_manager_record_finding_appends_and_updates_count() -> None:
    """A successfully recorded finding must appear in `findings` with `findings_count` updated."""
    writer = StateWriter(_base_state())
    manager = ReviewManager(writer)

    manager.record_finding(
        "requirements_review",
        {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
    )

    review = writer.review("requirements_review")
    assert len(review.findings) == 1
    assert review.findings[0].id == "R1-F1"
    assert review.findings_count == 1


def test_review_manager_record_finding_rejects_duplicate_ids() -> None:
    """Re-recording an existing finding ID must fail fast."""
    writer = StateWriter(_base_state())
    manager = ReviewManager(writer)

    manager.record_finding(
        "requirements_review",
        {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
    )

    with pytest.raises(StateMutationError):
        manager.record_finding(
            "requirements_review",
            {"id": "R1-F1", "severity": "minor", "summary": "Duplicate", "status": "open"},
        )

    # The original record must remain unchanged after the rejection.
    review = writer.review("requirements_review")
    assert len(review.findings) == 1
    assert review.findings[0].severity == "critical"


def test_review_manager_record_finding_rejects_missing_id() -> None:
    """Records without a stable `id` must be rejected."""
    writer = StateWriter(_base_state())
    manager = ReviewManager(writer)

    with pytest.raises(StateMutationError):
        manager.record_finding(
            "requirements_review",
            {"severity": "critical", "summary": "missing id"},
        )


def test_review_manager_resolve_finding_sets_resolved_fields() -> None:
    """Resolving a known finding must flip status and record the resolution method."""
    state = _base_state()
    state["requirements_review"] = {
        "findings": [
            {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
        ]
    }
    writer = StateWriter(state)
    manager = ReviewManager(writer)

    resolved = manager.resolve_finding("requirements_review", "R1-F1", "updated artifact")

    assert resolved.status == "resolved"
    assert resolved.resolution_method == "updated artifact"
    assert resolved.resolved_at

    review = writer.review("requirements_review")
    assert review.findings[0].status == "resolved"


def test_review_manager_resolve_finding_rejects_unknown_id() -> None:
    """Resolving an unknown finding ID must fail fast, not silently skip."""
    state = _base_state()
    state["requirements_review"] = {
        "findings": [
            {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
        ]
    }
    writer = StateWriter(state)
    manager = ReviewManager(writer)

    with pytest.raises(StateMutationError):
        manager.resolve_finding("requirements_review", "NONEXISTENT", "fixed")

    # The existing finding must remain open.
    review = writer.review("requirements_review")
    assert review.findings[0].status == "open"


def test_review_manager_record_finding_full_commit_round_trip() -> None:
    """Committing after `record_finding` must emit a single persisted payload."""
    writer = StateWriter(_base_state())
    manager = ReviewManager(writer)
    manager.record_finding(
        "plan_review",
        {"id": "PR-F1", "severity": "substantive", "summary": "needs change", "status": "open"},
    )

    todos_db = MagicMock(spec=TodosDb)

    payload = writer.commit_sync(todos_db, "slug-commit")

    todos_db.write_state_sync.assert_called_once_with("slug-commit", payload)
    review = cast(dict[str, StateValue], payload["plan_review"])
    findings = cast(list[dict[str, StateValue]], review["findings"])
    assert findings[0]["id"] == "PR-F1"

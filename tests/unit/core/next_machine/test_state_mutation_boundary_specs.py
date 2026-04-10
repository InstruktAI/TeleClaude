# guard: no-companion
"""Executable specs for the state-machine-abstraction typed mutation boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api.todo_routes import stamp, todo_mark_phase
from teleclaude.core import todos_db as todos_db_module
from teleclaude.core.next_machine import state_io as state_io_module
from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD, PreparePhase, StateValue
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.prepare_events import invalidate_stale_preparations
from teleclaude.core.next_machine.prepare_helpers import record_finding, resolve_finding
from teleclaude.core.next_machine.state_io import mark_phase, read_phase_state
from teleclaude.core.todos_db import TodosDb

pytestmark = [
    pytest.mark.unit,
    pytest.mark.timeout(10),
]

StateData = dict[str, StateValue]


@pytest.fixture(autouse=True)
def _clear_todos_db_caches() -> Iterator[None]:
    """Keep per-test TodosDb instances isolated."""
    # pylint: disable=protected-access
    todos_db_module._instances.clear()
    state_io_module._db_cache.clear()
    yield
    todos_db_module._instances.clear()
    state_io_module._db_cache.clear()
    # pylint: enable=protected-access


def _init_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a todos.db with the repo schema."""
    db_path = str(tmp_path / ".teleclaude" / "todos.db")
    TodosDb(db_path).initialize_sync()
    return sqlite3.connect(db_path)


def _ensure_roadmap(conn: sqlite3.Connection, slug: str) -> None:
    """Insert an active roadmap row for *slug*."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
        "VALUES (?, ?, 0, 'active', ?, ?)",
        (slug, slug, now, now),
    )
    conn.commit()


def _write_state_db(conn: sqlite3.Connection, slug: str, state: StateData) -> None:
    """Persist a raw todo state payload for test setup."""
    now = datetime.now(UTC).isoformat()
    _ensure_roadmap(conn, slug)
    conn.execute(
        "INSERT INTO todo_state (id, slug, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "  # guard: raw-sql
        "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
        (slug, slug, json.dumps(state), now, now),
    )
    conn.commit()


def _write_artifact_db(conn: sqlite3.Connection, slug: str, name: str, content: str) -> None:
    """Persist a DB-backed artifact for test setup."""
    now = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _ensure_roadmap(conn, slug)
    conn.execute(
        "INSERT INTO todo_artifacts (id, slug, name, content, digest, updated_by, updated_at) "  # guard: raw-sql
        "VALUES (?, ?, ?, ?, ?, 'spec-test', ?) "
        "ON CONFLICT(id, name) DO UPDATE SET "
        "content = excluded.content, digest = excluded.digest, updated_at = excluded.updated_at",
        (slug, slug, name, content, digest, now),
    )
    conn.commit()


def _identity_path(path: str) -> str:
    return path


def _assert_boundary_rejection(error: HTTPException) -> None:
    """Assert an API surface rejected a malformed persisted state."""
    assert error.status_code in (409, 422)
    assert str(error.detail)


def _assert_persisted_state_unchanged(cwd: Path, slug: str, expected_state: StateData) -> None:
    """Assert a rejected mutation did not partially persist any state changes."""
    assert read_phase_state(str(cwd), slug) == expected_state


@dataclass
class _InMemoryTodosDb:
    """Minimal async TodosDb stand-in for public prepare entrypoint specs."""

    state: StateData

    async def slug_in_roadmap(self, _slug: str) -> bool:
        """Pretend every requested slug already exists."""
        return True

    async def add_to_roadmap(self, _slug: str) -> None:
        """Avoid mutating roadmap state in the in-memory double."""
        return None

    async def read_state(self, _slug: str) -> StateData:
        """Return a defensive copy of the tracked state."""
        return copy.deepcopy(self.state)

    async def write_state(self, _slug: str, state: StateData) -> None:
        """Persist a defensive copy of the updated state."""
        self.state = copy.deepcopy(state)


@pytest.mark.asyncio
async def test_stamp_verdict_updates_phase_and_audit_verdict_together(tmp_path: Path) -> None:
    """R1/R3/R5: public stamp verdict updates phase + audit atomically."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-stamp-verdict",
        {
            "schema_version": 2,
            "current": "requirements_review",
            "requirements_review": {"verdict": "", "reviewed_at": "", "findings_count": 0},
            "audit": {"requirements_review": {"verdict": ""}},
        },
    )
    conn.close()

    with patch("teleclaude.api.todo_routes.resolve_canonical_project_root", side_effect=_identity_path):
        await stamp("slug-stamp-verdict", "verdict", "approve", cwd=str(tmp_path))

    state = read_phase_state(str(tmp_path), "slug-stamp-verdict")
    review = state.get("requirements_review")
    audit = state.get("audit")
    assert isinstance(review, dict)
    assert isinstance(audit, dict)
    audit_review = audit.get("requirements_review")
    assert isinstance(audit_review, dict)
    assert review["verdict"] == "approve"
    assert audit_review["verdict"] == "approve"


@pytest.mark.asyncio
async def test_stamp_grounding_rejects_malformed_grounding_state_instead_of_coercing(tmp_path: Path) -> None:
    """R1/R2/R4/R5: malformed grounding state must be rejected, not repaired in place."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-stamp-grounding",
        {"schema_version": 2, "current": "requirements_review", "grounding": ["not-a-grounding-dict"]},
    )
    conn.close()
    expected_state = read_phase_state(str(tmp_path), "slug-stamp-grounding")

    with patch("teleclaude.api.todo_routes.resolve_canonical_project_root", side_effect=_identity_path):
        with pytest.raises(HTTPException) as exc_info:
            await stamp("slug-stamp-grounding", "grounding", "valid", cwd=str(tmp_path))

    _assert_boundary_rejection(exc_info.value)
    _assert_persisted_state_unchanged(tmp_path, "slug-stamp-grounding", expected_state)


@pytest.mark.asyncio
async def test_stamp_dor_rejects_malformed_dor_state_instead_of_coercing(tmp_path: Path) -> None:
    """R1/R4/R5: DOR stamps fail fast when persisted state shape is invalid."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-stamp-dor", {"schema_version": 2, "current": "gate", "dor": "broken"})
    conn.close()
    expected_state = read_phase_state(str(tmp_path), "slug-stamp-dor")

    with patch("teleclaude.api.todo_routes.resolve_canonical_project_root", side_effect=_identity_path):
        with pytest.raises(HTTPException) as exc_info:
            await stamp("slug-stamp-dor", "dor", "score:9,status:pass", cwd=str(tmp_path))

    _assert_boundary_rejection(exc_info.value)
    _assert_persisted_state_unchanged(tmp_path, "slug-stamp-dor", expected_state)


@pytest.mark.asyncio
async def test_mark_phase_verdict_updates_phase_and_audit_verdict_together(tmp_path: Path) -> None:
    """R1/R3/R5: public mark-phase verdict stamps cannot diverge from audit state."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-mark-verdict",
        {
            "schema_version": 2,
            "current": "requirements_review",
            "requirements_review": {"verdict": "", "reviewed_at": "", "findings_count": 0},
            "audit": {"requirements_review": {"verdict": ""}},
        },
    )
    conn.close()

    with patch("teleclaude.api.todo_routes.resolve_canonical_project_root", side_effect=_identity_path):
        await todo_mark_phase(
            slug="slug-mark-verdict",
            phase="requirements_review",
            status="approve",
            cwd=str(tmp_path),
            _identity=SimpleNamespace(session_id="reviewer"),
            force=False,
        )

    state = read_phase_state(str(tmp_path), "slug-mark-verdict")
    review = state.get("requirements_review")
    audit = state.get("audit")
    assert isinstance(review, dict)
    assert isinstance(audit, dict)
    audit_review = audit.get("requirements_review")
    assert isinstance(audit_review, dict)
    assert review["verdict"] == "approve"
    assert audit_review["verdict"] == "approve"


@pytest.mark.asyncio
async def test_mark_phase_artifact_stamp_rejects_malformed_artifacts_state_instead_of_coercing(tmp_path: Path) -> None:
    """R1/R4/R5: artifact stamps fail fast on malformed persisted artifact state."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-mark-artifact", {"schema_version": 2, "artifacts": ["broken"]})
    conn.close()
    expected_state = read_phase_state(str(tmp_path), "slug-mark-artifact")

    with patch("teleclaude.api.todo_routes.resolve_canonical_project_root", side_effect=_identity_path):
        with pytest.raises(HTTPException) as exc_info:
            await todo_mark_phase(
                slug="slug-mark-artifact",
                phase="requirements",
                status="complete",
                cwd=str(tmp_path),
                _identity=SimpleNamespace(session_id="reviewer"),
                force=False,
            )

    _assert_boundary_rejection(exc_info.value)
    _assert_persisted_state_unchanged(tmp_path, "slug-mark-artifact", expected_state)


def test_invalidate_stale_preparations_rejects_malformed_grounding_state(tmp_path: Path) -> None:
    """R1/R2/R4: event-driven invalidation must fail fast on malformed state."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-invalidation", {"schema_version": 2, "grounding": "broken"})
    conn.close()
    expected_state = read_phase_state(str(tmp_path), "slug-invalidation")

    with (
        patch("teleclaude.core.next_machine.prepare_events.resolve_main_repo_root", return_value=tmp_path),
        patch("teleclaude.core.next_machine.prepare_events._emit_prepare_event"),
    ):
        with pytest.raises((TypeError, ValueError)):
            invalidate_stale_preparations(str(tmp_path), ["src/app.py"])

    _assert_persisted_state_unchanged(tmp_path, "slug-invalidation", expected_state)


@pytest.mark.parametrize("review_type", ["requirements_review", "plan_review"])
def test_review_finding_boundary_preserves_stable_ids_and_resolved_status(tmp_path: Path, review_type: str) -> None:
    """R3: review finding mutations preserve stable IDs and open/resolved semantics."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        f"slug-{review_type}-findings",
        {
            "schema_version": 2,
            "current": review_type,
            review_type: {"verdict": "", "reviewed_at": "", "findings_count": 0, "findings": []},
        },
    )
    conn.close()

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        record_finding(
            str(tmp_path),
            f"slug-{review_type}-findings",
            review_type,
            {"id": "R3-F1", "severity": "substantive", "summary": "first", "status": "open"},
        )
        record_finding(
            str(tmp_path),
            f"slug-{review_type}-findings",
            review_type,
            {"id": "R3-F2", "severity": "substantive", "summary": "second", "status": "open"},
        )
        resolve_finding(str(tmp_path), f"slug-{review_type}-findings", review_type, "R3-F1", "updated artifact")

    state = read_phase_state(str(tmp_path), f"slug-{review_type}-findings")
    review = state.get(review_type)
    assert isinstance(review, dict)
    findings = review.get("findings")
    assert isinstance(findings, list)
    assert review["findings_count"] == 2

    finding_records = [finding for finding in findings if isinstance(finding, dict)]
    assert [finding.get("id") for finding in finding_records] == ["R3-F1", "R3-F2"]
    assert finding_records[0]["status"] == "resolved"
    assert finding_records[0]["resolved_at"]
    assert finding_records[1]["status"] == "open"


def test_resolve_finding_unknown_id_rejects_instead_of_silently_skipping(tmp_path: Path) -> None:
    """R3: resolving a non-existent finding ID must fail fast, not silently return."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-resolve-unknown",
        {
            "schema_version": 2,
            "current": "requirements_review",
            "requirements_review": {
                "verdict": "needs_work",
                "findings": [
                    {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
                ],
            },
        },
    )
    conn.close()
    expected_state = read_phase_state(str(tmp_path), "slug-resolve-unknown")

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        with pytest.raises((KeyError, ValueError)):
            resolve_finding(str(tmp_path), "slug-resolve-unknown", "requirements_review", "NONEXISTENT", "fixed")

    _assert_persisted_state_unchanged(tmp_path, "slug-resolve-unknown", expected_state)


def test_record_finding_rejects_duplicate_ids_in_review_state(tmp_path: Path) -> None:
    """R3: recording a duplicate finding ID must fail fast instead of duplicating review findings."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-duplicate-findings",
        {
            "schema_version": 2,
            "current": "requirements_review",
            "requirements_review": {
                "findings": [
                    {"id": "R1-F1", "severity": "critical", "summary": "Bug A", "status": "open"},
                ],
            },
        },
    )
    conn.close()
    expected_state = read_phase_state(str(tmp_path), "slug-duplicate-findings")

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        with pytest.raises((KeyError, ValueError)):
            record_finding(
                str(tmp_path),
                "slug-duplicate-findings",
                "requirements_review",
                {"id": "R1-F1", "severity": "important", "summary": "Duplicate", "status": "open"},
            )

    _assert_persisted_state_unchanged(tmp_path, "slug-duplicate-findings", expected_state)


@pytest.mark.asyncio
async def test_next_prepare_does_not_dispatch_re_grounding_twice_for_same_sha() -> None:
    """R2: once a re-grounding cycle finishes, the next public prepare pass must not loop again.

    After grounding is invalidated and a re-grounding dispatch is issued, the stored
    grounding baseline must be refreshed to the current HEAD.  When the prepare lifecycle
    re-enters grounding_check the baseline will then match HEAD, preventing a second
    dispatch for the same SHA.
    """
    todos_db = _InMemoryTodosDb(
        {
            "schema_version": 2,
            "current": PreparePhase.GROUNDING_CHECK.value,
            "dor": {"score": DOR_READY_THRESHOLD},
            "grounding": {"base_sha": "oldsha", "input_digest": "", "referenced_paths": []},
        }
    )

    def _run_git_command(args: list[str], **_kwargs: object) -> tuple[int, str, str]:
        if args[:2] == ["rev-parse", "HEAD"]:
            return 0, "newsha\n", ""
        return 0, "", ""

    with (
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.next_machine.slug_resolution.resolve_holder_children_db", return_value=[]),
        patch("teleclaude.core.next_machine.prepare.check_artifact_staleness_db", return_value=[]),
        patch("teleclaude.core.next_machine.prepare_steps.run_git_command", side_effect=_run_git_command),
    ):
        await next_prepare(AsyncMock(), "slug-loop", "/repo")

        # After the re-grounding dispatch the stored baseline must already be "newsha".
        # Without the refresh, the second grounding_check would see the same delta and
        # dispatch a second re-grounding for the same SHA — the known loop bug.
        grounding = todos_db.state.get("grounding")
        assert isinstance(grounding, dict)
        assert grounding.get("base_sha") == "newsha"

        # Simulate the prepare machine re-entering grounding_check after the re-grounding cycle.
        todos_db.state["current"] = PreparePhase.GROUNDING_CHECK.value

        await next_prepare(AsyncMock(), "slug-loop", "/repo")

    # With the refreshed baseline the second pass must advance to prepared, not re-dispatch.
    assert todos_db.state.get("current") == PreparePhase.PREPARED.value


def test_mark_phase_prepared_updates_review_audit_verdicts_with_phase_verdicts(tmp_path: Path) -> None:
    """R1/R3: work-lifecycle prepared transition keeps visible verdicts and audit in sync."""
    conn = _init_db(tmp_path)
    _write_artifact_db(conn, "slug-prepared", "requirements", "real requirements\n")
    _write_artifact_db(conn, "slug-prepared", "implementation-plan", "real plan\n")
    _write_artifact_db(conn, "slug-prepared", "input", "input\n")
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root",
            side_effect=_identity_path,
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.run_git_command", return_value=(0, "headsha\n", "")),
    ):
        state = mark_phase(str(tmp_path), "slug-prepared", "prepared")

    requirements_review = state.get("requirements_review")
    plan_review = state.get("plan_review")
    audit = state.get("audit")
    assert isinstance(requirements_review, dict)
    assert isinstance(plan_review, dict)
    assert isinstance(audit, dict)
    audit_requirements = audit.get("requirements_review")
    audit_plan = audit.get("plan_review")
    assert isinstance(audit_requirements, dict)
    assert isinstance(audit_plan, dict)
    assert requirements_review["verdict"] == "approve"
    assert plan_review["verdict"] == "approve"
    assert audit_requirements["verdict"] == "approve"
    assert audit_plan["verdict"] == "approve"

from __future__ import annotations

# guard: no-companion
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.slug_resolution import is_ready_for_work
from teleclaude.core.next_machine.state_io import read_phase_state

pytestmark = [
    pytest.mark.unit,
]


def _write_state(todo_dir: Path, state: dict[str, StateValue]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")


def test_read_phase_state_migrates_legacy_prepare_state_into_v2_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-a",
        {
            "schema_version": 1,
            "phase": "pending",
            "build": "pending",
            "review": "pending",
            "prepare_phase": "plan_review",
        },
    )

    state = read_phase_state(str(tmp_path), "slug-a")

    assert state["schema_version"] == 2
    assert state["current"] == "plan_review"
    assert state["history"] == []
    assert "prepare_phase" not in state
    assert "build" not in state
    assert "review" not in state


def test_read_phase_state_keeps_existing_v2_blob_without_reintroducing_legacy_fields(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-b",
        {
            "schema_version": 2,
            "current": "requirements_review",
            "history": [
                {
                    "source": "input_assessment",
                    "target": "requirements_review",
                    "transition": "produce_requirements",
                    "at": "2025-01-01T00:00:00+00:00",
                    "by": "session-123",
                    "metadata": {"digest": "abc123"},
                }
            ],
        },
    )

    state = read_phase_state(str(tmp_path), "slug-b")

    assert state == {
        "schema_version": 2,
        "current": "requirements_review",
        "history": [
            {
                "source": "input_assessment",
                "target": "requirements_review",
                "transition": "produce_requirements",
                "at": "2025-01-01T00:00:00+00:00",
                "by": "session-123",
                "metadata": {"digest": "abc123"},
            }
        ],
    }


@pytest.mark.asyncio
async def test_next_prepare_routes_from_current_without_phase_derivation() -> None:
    dispatch = AsyncMock(return_value=(False, "STATE ROUTED"))
    todos_db = AsyncMock()
    todos_db.slug_in_roadmap = AsyncMock(return_value=True)
    todos_db.read_state = AsyncMock(
        return_value={
            "schema_version": 2,
            "current": "plan_review",
            "prepare_phase": "input_assessment",
            "history": [],
        }
    )

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", return_value="/tmp/project"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch("teleclaude.core.next_machine.prepare.check_artifact_staleness_db", return_value=[]),
        patch("teleclaude.core.next_machine.prepare._prepare_dispatch", dispatch),
    ):
        result = await next_prepare(MagicMock(), "slug-a", "/tmp/project")

    assert result == "STATE ROUTED"
    assert dispatch.await_count == 1
    assert dispatch.await_args.kwargs["phase"] == PreparePhase.PLAN_REVIEW


# ---------------------------------------------------------------------------
# _migrate_v1_to_v2 branch coverage (I5)
# ---------------------------------------------------------------------------


def test_v1_finalize_handed_off_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-fh",
        {
            "phase": "in_progress",
            "build": "complete",
            "review": "approved",
            "finalize": {"status": "handed_off", "branch": "slug-fh", "sha": "abc123"},
        },
    )
    state = read_phase_state(str(tmp_path), "slug-fh")
    assert state["current"] == "finalize_handed_off"
    assert "build" not in state
    assert "review" not in state


def test_v1_finalize_ready_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-fr",
        {
            "phase": "in_progress",
            "build": "complete",
            "review": "approved",
            "finalize": {"status": "ready", "branch": "slug-fr", "sha": "def456"},
        },
    )
    state = read_phase_state(str(tmp_path), "slug-fr")
    assert state["current"] == "finalize_ready"


def test_v1_review_approved_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-ra",
        {"phase": "in_progress", "build": "complete", "review": "approved"},
    )
    state = read_phase_state(str(tmp_path), "slug-ra")
    assert state["current"] == "review_approved"


def test_v1_review_changes_requested_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-rc",
        {"phase": "in_progress", "build": "complete", "review": "changes_requested"},
    )
    state = read_phase_state(str(tmp_path), "slug-rc")
    assert state["current"] == "review_changes_requested"


def test_v1_review_pending_with_build_complete_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-rp",
        {"phase": "in_progress", "build": "complete", "review": "pending"},
    )
    state = read_phase_state(str(tmp_path), "slug-rp")
    assert state["current"] == "review_pending"


def test_v1_build_complete_without_review_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-bc",
        {"phase": "in_progress", "build": "complete", "review": ""},
    )
    state = read_phase_state(str(tmp_path), "slug-bc")
    assert state["current"] == "build_complete"


def test_v1_build_started_migrates_to_current(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-bs",
        {"phase": "in_progress", "build": "started", "review": "pending"},
    )
    state = read_phase_state(str(tmp_path), "slug-bs")
    assert state["current"] == "build_started"


def test_v1_fallback_to_input_assessment(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-fb",
        {"phase": "pending", "build": "pending", "review": "pending"},
    )
    state = read_phase_state(str(tmp_path), "slug-fb")
    assert state["current"] == "input_assessment"


# ---------------------------------------------------------------------------
# is_ready_for_work
# ---------------------------------------------------------------------------


def test_is_ready_for_work_uses_current_authoritative_state_value() -> None:
    with patch(
        "teleclaude.core.next_machine.slug_resolution.read_phase_state",
        side_effect=[
            {"schema_version": 2, "current": "prepared", "history": []},
            {"schema_version": 2, "current": "requirements_review", "history": []},
        ],
    ):
        assert is_ready_for_work("/tmp/project", "slug-a") is True
        assert is_ready_for_work("/tmp/project", "slug-b") is False

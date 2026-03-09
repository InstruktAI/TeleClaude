"""Tests for next_prepare() state machine — replaces hitl-based tests."""

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    format_tool_call,
    get_stash_entries,
    has_git_stash_entries,
    has_uncommitted_changes,
    is_build_complete,
    is_review_approved,
    is_review_changes_requested,
    mark_phase,
    next_prepare,
    read_phase_state,
    sync_main_to_worktree,
    write_phase_state,
)
from teleclaude.core.next_machine.core import PreparePhase


# =============================================================================
# Precondition tests (pre-dispatch)
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_no_slug_returns_tool_call():
    """next_prepare with no resolvable slug dispatches next-prepare-draft."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with patch("teleclaude.core.next_machine.core._find_next_prepare_slug", return_value=None):
        result = await next_prepare(db, slug=None, cwd=cwd)
        assert "next-prepare-draft" in result
        assert "No active preparation work found" in result


@pytest.mark.asyncio
async def test_prepare_slug_missing_from_roadmap_auto_adds():
    """next_prepare auto-adds slug to roadmap when missing, then proceeds to dispatch."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with (
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=False),
        patch("teleclaude.core.next_machine.core.add_to_roadmap") as mock_add,
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value={"prepare_phase": ""}),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        mock_add.assert_called_once_with(cwd, slug)
        assert "next-prepare-discovery" in result


# =============================================================================
# Phase handler tests
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_missing_requirements_dispatches_discovery():
    """DISCOVERY phase dispatches next-prepare-discovery when requirements.md is missing."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.DISCOVERY.value,
        "breakdown": {"assessed": True, "todos": []},
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-discovery" in result
        assert f'--args "{slug}"' in result


@pytest.mark.asyncio
async def test_prepare_missing_plan_dispatches_draft():
    """PLAN_DRAFTING phase dispatches next-prepare-draft when implementation-plan.md missing."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.PLAN_DRAFTING.value,
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-draft" in result
        assert "implementation-plan.md" in result


@pytest.mark.asyncio
async def test_prepare_both_exist_dispatches_gate():
    """GATE phase dispatches next-prepare-gate when DOR score is below threshold."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.GATE.value,
        "dor": {"score": 5},
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-gate" in result


@pytest.mark.asyncio
async def test_prepare_requirements_review_approve_transitions_to_plan():
    """REQUIREMENTS_REVIEW with approve verdict transitions to PLAN_DRAFTING."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    # Drift check reads state once, then loop reads twice:
    # REQUIREMENTS_REVIEW approved → transitions to PLAN_DRAFTING → dispatches next-prepare-draft
    drift_state = {
        "prepare_phase": PreparePhase.REQUIREMENTS_REVIEW.value,
        "requirements_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0},
    }
    states = [
        drift_state,  # drift check
        {
            "prepare_phase": PreparePhase.REQUIREMENTS_REVIEW.value,
            "requirements_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0},
        },
        {
            "prepare_phase": PreparePhase.PLAN_DRAFTING.value,
            "requirements_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0},
        },
    ]
    state_iter = iter(states)

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=lambda *_: next(state_iter)),
        patch("teleclaude.core.next_machine.core.write_phase_state"),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-draft" in result
        assert "implementation-plan.md" in result


@pytest.mark.asyncio
async def test_prepare_requirements_review_needs_work_loops_back():
    """REQUIREMENTS_REVIEW with needs_work loops back to DISCOVERY."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.REQUIREMENTS_REVIEW.value,
        "requirements_review": {"verdict": "needs_work", "reviewed_at": "", "findings_count": 1},
    }

    # After loop-back to DISCOVERY, requirements.md still absent → dispatches discovery
    written_state = {}

    def fake_write(w_cwd, w_slug, s):
        written_state.update(s)

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch(
            "teleclaude.core.next_machine.core.read_phase_state",
            side_effect=[state, state, {**state, "prepare_phase": PreparePhase.DISCOVERY.value}],
        ),
        patch("teleclaude.core.next_machine.core.write_phase_state", side_effect=fake_write),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-discovery" in result
        assert written_state.get("prepare_phase") == PreparePhase.DISCOVERY.value


@pytest.mark.asyncio
async def test_prepare_plan_review_approve_transitions_to_gate():
    """PLAN_REVIEW with approve verdict transitions to GATE."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    drift_state = {
        "prepare_phase": PreparePhase.PLAN_REVIEW.value,
        "plan_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0},
    }
    states = [
        drift_state,  # drift check
        {
            "prepare_phase": PreparePhase.PLAN_REVIEW.value,
            "plan_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0},
        },
        {
            "prepare_phase": PreparePhase.GATE.value,
            "dor": {"score": 5},
        },
    ]
    state_iter = iter(states)

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=lambda *_: next(state_iter)),
        patch("teleclaude.core.next_machine.core.write_phase_state"),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-gate" in result


@pytest.mark.asyncio
async def test_prepare_plan_review_needs_work_loops_back():
    """PLAN_REVIEW with needs_work loops back to PLAN_DRAFTING."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.PLAN_REVIEW.value,
        "plan_review": {"verdict": "needs_work", "reviewed_at": "", "findings_count": 2},
    }

    written_state = {}

    def fake_write(w_cwd, w_slug, s):
        written_state.update(s)

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch(
            "teleclaude.core.next_machine.core.read_phase_state",
            side_effect=[state, state, {**state, "prepare_phase": PreparePhase.PLAN_DRAFTING.value}],
        ),
        patch("teleclaude.core.next_machine.core.write_phase_state", side_effect=fake_write),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-draft" in result
        assert written_state.get("prepare_phase") == PreparePhase.PLAN_DRAFTING.value


@pytest.mark.asyncio
async def test_prepare_gate_pass_transitions_to_grounding():
    """GATE with DOR score >= 8 transitions to GROUNDING_CHECK."""
    db = MagicMock(spec=Db)
    slug = "test-slug"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Grounding check will look for input.md
        todo_dir = Path(tmpdir) / "todos" / slug
        todo_dir.mkdir(parents=True)

        grounding_state = {
            "valid": False,
            "base_sha": "",  # empty triggers first-grounding path → PREPARED
            "input_digest": "",
            "referenced_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "",
            "invalidation_reason": "",
        }

        # We need 3 states: GATE → write GROUNDING_CHECK → read GROUNDING_CHECK → write PREPARED → read PREPARED
        # Use a cycling state so StopIteration never occurs
        phase_states = [
            {
                "prepare_phase": PreparePhase.GATE.value,
                "dor": {"score": 9},
                "grounding": dict(grounding_state),
            },
            {
                "prepare_phase": PreparePhase.GROUNDING_CHECK.value,
                "grounding": dict(grounding_state),
            },
            {
                "prepare_phase": PreparePhase.PREPARED.value,
                "grounding": {**grounding_state, "valid": True, "base_sha": "cur"},
            },
        ]
        call_count = 0

        def cycling_state(*_args):
            nonlocal call_count
            idx = min(call_count, len(phase_states) - 1)
            call_count += 1
            return phase_states[idx]

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=cycling_state),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch("teleclaude.core.next_machine.core.sync_main_to_worktree"),
            patch(
                "teleclaude.core.next_machine.core._run_git_prepare",
                return_value=(0, "cur_sha", ""),
            ),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=tmpdir)
            # Should reach PREPARED
            assert "PREPARED" in result


@pytest.mark.asyncio
async def test_prepare_gate_fail_transitions_to_blocked_via_gate_dispatch():
    """GATE with DOR score < 8 dispatches gate worker."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.GATE.value,
        "dor": {"score": 4},
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-gate" in result


@pytest.mark.asyncio
async def test_prepare_grounding_check_fresh_transitions_to_prepared():
    """GROUNDING_CHECK with matching digests transitions to PREPARED."""
    db = MagicMock(spec=Db)
    slug = "test-slug"

    with tempfile.TemporaryDirectory() as tmpdir:
        todo_dir = Path(tmpdir) / "todos" / slug
        todo_dir.mkdir(parents=True)

        state = {
            "prepare_phase": PreparePhase.GROUNDING_CHECK.value,
            "grounding": {
                "valid": False,
                "base_sha": "abc123",
                "input_digest": "",
                "referenced_paths": [],
                "last_grounded_at": "",
                "invalidated_at": "",
                "invalidation_reason": "",
            },
        }

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=[state, state, state]),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch(
                "teleclaude.core.next_machine.core._run_git_prepare",
                return_value=(0, "abc123", ""),
            ),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=tmpdir)
            assert "PREPARED" in result


@pytest.mark.asyncio
async def test_prepare_grounding_check_stale_transitions_to_regrounding():
    """GROUNDING_CHECK with differing SHA transitions to RE_GROUNDING."""
    db = MagicMock(spec=Db)
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "prepare_phase": PreparePhase.GROUNDING_CHECK.value,
            "grounding": {
                "valid": True,
                "base_sha": "old_sha",
                "input_digest": "",
                "referenced_paths": [],
                "last_grounded_at": "",
                "invalidated_at": "",
                "invalidation_reason": "",
            },
        }

        # After RE_GROUNDING transition, provide PLAN_REVIEW state for dispatch
        re_ground_state = {
            "prepare_phase": PreparePhase.RE_GROUNDING.value,
            "grounding": {
                "valid": False,
                "base_sha": "old_sha",
                "input_digest": "",
                "referenced_paths": [],
                "last_grounded_at": "",
                "invalidated_at": "2026-01-01T00:00:00+00:00",
                "invalidation_reason": "files_changed",
            },
        }

        states = [state, state, re_ground_state]  # drift check + 2 loop iterations
        state_iter = iter(states)

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=lambda *_: next(state_iter)),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch(
                "teleclaude.core.next_machine.core._run_git_prepare",
                return_value=(0, "new_sha", ""),
            ),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=tmpdir)
            assert "next-prepare-draft" in result


@pytest.mark.asyncio
async def test_prepare_grounding_check_sha_only_change_with_references_stays_prepared():
    """GROUNDING_CHECK ignores unrelated HEAD changes when referenced paths are unchanged."""
    db = MagicMock(spec=Db)
    slug = "test-slug"

    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "prepare_phase": PreparePhase.GROUNDING_CHECK.value,
            "grounding": {
                "valid": True,
                "base_sha": "old_sha",
                "input_digest": "",
                "referenced_paths": ["src/foo.py"],
                "last_grounded_at": "",
                "invalidated_at": "",
                "invalidation_reason": "",
            },
        }

        def mock_run_git_prepare(args: list[str], cwd: str) -> tuple[int, str, str]:
            if args[:2] == ["rev-parse", "HEAD"]:
                return (0, "new_sha", "")
            if args[:2] == ["diff", "--name-only"]:
                return (0, "docs/unrelated.md\n", "")
            return (1, "", "")

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch("teleclaude.core.next_machine.core._run_git_prepare", side_effect=mock_run_git_prepare),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=tmpdir)
            assert "PREPARED" in result


@pytest.mark.asyncio
async def test_prepare_grounding_check_empty_stored_digest_backfills_without_regrounding():
    """GROUNDING_CHECK should backfill missing input_digest instead of forcing re-grounding."""
    db = MagicMock(spec=Db)
    slug = "test-slug"

    with tempfile.TemporaryDirectory() as tmpdir:
        todo_dir = Path(tmpdir) / "todos" / slug
        todo_dir.mkdir(parents=True)
        input_text = "hello grounding\n"
        (todo_dir / "input.md").write_text(input_text, encoding="utf-8")

        state = {
            "prepare_phase": PreparePhase.GROUNDING_CHECK.value,
            "grounding": {
                "valid": True,
                "base_sha": "same_sha",
                "input_digest": "",
                "referenced_paths": ["src/foo.py"],
                "last_grounded_at": "",
                "invalidated_at": "",
                "invalidation_reason": "",
            },
        }

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch("teleclaude.core.next_machine.core._run_git_prepare", return_value=(0, "same_sha", "")),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=tmpdir)
            assert "PREPARED" in result
            assert state["grounding"]["input_digest"] == hashlib.sha256(input_text.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_prepare_regrounding_dispatches_draft_with_changes():
    """RE_GROUNDING phase dispatches next-prepare-draft with changed paths note."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.RE_GROUNDING.value,
        "grounding": {
            "valid": False,
            "base_sha": "old",
            "input_digest": "",
            "referenced_paths": ["src/foo.py"],
            "last_grounded_at": "",
            "invalidated_at": "2026-01-01T00:00:00+00:00",
            "invalidation_reason": "files_changed",
        },
        "plan_review": {"verdict": "", "reviewed_at": "", "findings_count": 0},
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core.write_phase_state"),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-draft" in result
        assert "implementation-plan.md" in result


@pytest.mark.asyncio
async def test_prepare_event_emission_at_transitions():
    """Event emission is called at phase transitions."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.REQUIREMENTS_REVIEW.value,
        "requirements_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0},
    }
    # Drift check + after approve, transition to PLAN_DRAFTING, then dispatch draft
    states = [
        state,  # drift check
        state,
        {
            "prepare_phase": PreparePhase.PLAN_DRAFTING.value,
            "requirements_review": {"verdict": "approve"},
        },
    ]
    state_iter = iter(states)
    emitted_events: list[str] = []

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=lambda *_: next(state_iter)),
        patch("teleclaude.core.next_machine.core.write_phase_state"),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch(
            "teleclaude.core.next_machine.core._emit_prepare_event",
            side_effect=lambda et, _: emitted_events.append(et),
        ),
    ):
        await next_prepare(db, slug=slug, cwd=cwd)
        assert "domain.software-development.prepare.requirements_approved" in emitted_events


@pytest.mark.asyncio
async def test_prepare_loop_limit_returns_error():
    """State machine returns LOOP_LIMIT error if it cycles too many times."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    # State that always loops (invalid phase string that triggers re-derivation,
    # but derivation returns DISCOVERY which dispatches, so use a handler
    # that always returns loop=True by giving a state that cycles).
    # Simplest: provide GROUNDING_CHECK state that always reports stale but
    # RE_GROUNDING always writes GROUNDING_CHECK back — impossible with patching.
    # Instead: exhaust loop with PreparePhase.GROUNDING_CHECK that returns (True,"")
    # by patching _prepare_step_grounding_check.
    from teleclaude.core.next_machine import core as cm

    original_loop_limit = cm._PREPARE_LOOP_LIMIT
    cm._PREPARE_LOOP_LIMIT = 3

    try:
        state = {
            "prepare_phase": PreparePhase.GROUNDING_CHECK.value,
            "grounding": {"base_sha": "x", "input_digest": "", "referenced_paths": [], "valid": False},
        }

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch(
                "teleclaude.core.next_machine.core._prepare_step_grounding_check",
                return_value=(True, ""),
            ),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=cwd)
            assert "LOOP_LIMIT" in result
    finally:
        cm._PREPARE_LOOP_LIMIT = original_loop_limit


# =============================================================================
# State Management Tests (preserved from original)
# =============================================================================


def test_read_phase_state_returns_default_when_no_file():
    """read_phase_state returns default state when state.yaml doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = read_phase_state(tmpdir, "test-slug")
        assert state["build"] == "pending"
        assert state["review"] == "pending"
        assert state["deferrals_processed"] is False
        assert state["breakdown"] == {"assessed": False, "todos": []}
        assert state["review_round"] == 0
        assert state["max_review_rounds"] == 3
        assert state["review_baseline_commit"] == ""
        assert state["unresolved_findings"] == []
        assert state["resolved_findings"] == []
        # New state machine keys
        assert state["prepare_phase"] == ""
        assert isinstance(state["grounding"], dict)
        assert isinstance(state["requirements_review"], dict)
        assert isinstance(state["plan_review"], dict)


def test_read_phase_state_reads_existing_file():
    """read_phase_state reads existing state.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.yaml"
        state_file.write_text(yaml.dump({"build": "complete", "review": "pending"}))

        state = read_phase_state(tmpdir, slug)
        assert state["build"] == "complete"
        assert state["review"] == "pending"
        assert state["deferrals_processed"] is False
        assert state["breakdown"] == {"assessed": False, "todos": []}
        assert state["review_round"] == 0
        assert state["max_review_rounds"] == 3
        assert state["review_baseline_commit"] == ""
        assert state["unresolved_findings"] == []
        assert state["resolved_findings"] == []


def test_write_phase_state_creates_file():
    """write_phase_state creates state.yaml and commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state = {"build": "complete", "review": "pending"}

        with patch("teleclaude.core.next_machine.core.Repo"):
            write_phase_state(tmpdir, slug, state)

        state_file = Path(tmpdir) / "todos" / slug / "state.yaml"
        assert state_file.exists()
        content = yaml.safe_load(state_file.read_text())
        assert content == state


def test_mark_phase_updates_state():
    """mark_phase updates state and returns updated dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "implementation-plan.md").write_text("- [x] Task 1\n- [x] Task 2\n")

        with patch("teleclaude.core.next_machine.core.Repo"):
            result = mark_phase(tmpdir, slug, "build", "complete")

        assert result["build"] == "complete"
        assert result["review"] == "pending"

        state_file = Path(tmpdir) / "todos" / slug / "state.yaml"
        content = yaml.safe_load(state_file.read_text())
        assert content["build"] == "complete"


def test_mark_phase_review_changes_requested_tracks_round_and_findings():
    """Review changes_requested increments round and captures finding IDs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "review-findings.md").write_text("# Findings\n- R1-F1\n- R1-F2\n")

        result = mark_phase(tmpdir, slug, "review", "changes_requested")

        assert result["review"] == "changes_requested"
        assert result["review_round"] == 1
        assert result["unresolved_findings"] == ["R1-F1", "R1-F2"]


def test_has_uncommitted_changes_ignores_orchestrator_control_files():
    """Dirty roadmap/dependencies alone should not block next_work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "trees" / "test-slug"
        worktree.mkdir(parents=True, exist_ok=True)

        repo_mock = MagicMock()
        repo_mock.git.status.return_value = " M todos/roadmap.yaml\n?? .teleclaude/\n"

        with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
            assert has_uncommitted_changes(tmpdir, "test-slug") is False


def test_has_uncommitted_changes_detects_non_control_file_changes():
    """Non-control dirty files must still block next_work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "trees" / "test-slug"
        worktree.mkdir(parents=True, exist_ok=True)

        repo_mock = MagicMock()
        repo_mock.git.status.return_value = " M teleclaude/core/next_machine/core.py\n"

        with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
            assert has_uncommitted_changes(tmpdir, "test-slug") is True


def test_has_uncommitted_changes_ignores_slug_todo_scaffold_paths():
    """Untracked synced slug todo files should not block next_work dispatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "trees" / "test-slug"
        worktree.mkdir(parents=True, exist_ok=True)

        repo_mock = MagicMock()
        repo_mock.git.status.return_value = "?? todos/test-slug/\n?? todos/test-slug/requirements.md\n"

        with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
            assert has_uncommitted_changes(tmpdir, "test-slug") is False


def test_get_stash_entries_returns_repo_stash_list():
    """Stash entries are repository-wide and should be detected for orchestration guardrails."""
    repo_mock = MagicMock()
    repo_mock.git.stash.return_value = "stash@{0}: WIP on test\nstash@{1}: On test"

    with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
        entries = get_stash_entries("/tmp/test")

    assert entries == ["stash@{0}: WIP on test", "stash@{1}: On test"]


def test_has_git_stash_entries_true_when_stash_not_empty():
    """Non-empty stash list should block workflow progression."""
    repo_mock = MagicMock()
    repo_mock.git.stash.return_value = "stash@{0}: WIP on test"

    with patch("teleclaude.core.next_machine.core.Repo", return_value=repo_mock):
        assert has_git_stash_entries("/tmp/test") is True


def test_sync_main_to_worktree_skips_when_inputs_unchanged():
    """Main planning sync should skip file copy when source and destination match."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_root = Path(tmpdir)
        worktree_root = main_root / "trees" / slug
        worktree_root.mkdir(parents=True, exist_ok=True)
        (main_root / "todos").mkdir(parents=True, exist_ok=True)
        (worktree_root / "todos").mkdir(parents=True, exist_ok=True)
        (main_root / "todos" / "roadmap.yaml").write_text("- slug: test-slug\n", encoding="utf-8")
        (worktree_root / "todos" / "roadmap.yaml").write_text("- slug: test-slug\n", encoding="utf-8")

        copied = sync_main_to_worktree(tmpdir, slug)

        assert copied == 0


def test_sync_main_to_worktree_copies_when_inputs_changed():
    """Main planning sync should copy roadmap when content differs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        main_root = Path(tmpdir)
        worktree_root = main_root / "trees" / slug
        worktree_root.mkdir(parents=True, exist_ok=True)
        (main_root / "todos").mkdir(parents=True, exist_ok=True)
        (worktree_root / "todos").mkdir(parents=True, exist_ok=True)
        (main_root / "todos" / "roadmap.yaml").write_text("- slug: changed\n", encoding="utf-8")
        (worktree_root / "todos" / "roadmap.yaml").write_text("- slug: stale\n", encoding="utf-8")

        copied = sync_main_to_worktree(tmpdir, slug)

        assert copied == 1
        assert "changed" in (worktree_root / "todos" / "roadmap.yaml").read_text(encoding="utf-8")


def test_mark_phase_review_approved_clears_unresolved_findings():
    """Review approved should clear unresolved findings and carry to resolved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(
            yaml.dump(
                {
                    "build": "complete",
                    "review": "pending",
                    "unresolved_findings": ["R1-F1"],
                    "resolved_findings": [],
                    "review_round": 1,
                }
            )
        )
        (state_dir / "review-findings.md").write_text("# Findings\n- R1-F1\n")

        result = mark_phase(tmpdir, slug, "review", "approved")

        assert result["review"] == "approved"
        assert result["review_round"] == 2
        assert result["unresolved_findings"] == []
        assert "R1-F1" in result["resolved_findings"]


def test_is_build_complete_true():
    """is_build_complete returns True when build is complete."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(yaml.dump({"build": "complete"}))

        assert is_build_complete(tmpdir, slug) is True


def test_is_build_complete_false():
    """is_build_complete returns False when build is pending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert is_build_complete(tmpdir, "test-slug") is False


def test_is_review_approved_true():
    """is_review_approved returns True when review is approved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(yaml.dump({"review": "approved"}))

        assert is_review_approved(tmpdir, slug) is True


def test_is_review_changes_requested_true():
    """is_review_changes_requested returns True when changes requested."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(yaml.dump({"review": "changes_requested"}))

        assert is_review_changes_requested(tmpdir, slug) is True


# =============================================================================
# format_tool_call Tests (preserved from original)
# =============================================================================


def test_format_tool_call_codex_uses_normalized_command():
    """format_tool_call keeps transport command payload stable for codex."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work",
    )
    assert '--command "/next-build"' in result
    assert "/prompts:" not in result
    assert 'telec sessions run --command "/next-build"' in result
    assert "telec sessions run --computer " not in result


def test_format_tool_call_claude_no_prefix():
    """format_tool_call does not rewrite command prefix for claude."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work",
    )
    assert '--command "/next-build"' in result
    assert "/prompts:" not in result
    assert 'telec sessions run --command "/next-build"' in result
    assert "telec sessions run --computer " not in result


def test_format_tool_call_gemini_no_prefix():
    """format_tool_call does not add prefix for gemini agent."""
    result = format_tool_call(
        command="next-review-build",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work",
    )
    assert '--command "/next-review-build"' in result
    assert "/prompts:" not in result


def test_format_tool_call_next_call_with_args():
    """format_tool_call preserves next_call arguments without double parentheses."""
    result = format_tool_call(
        command="next-build",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="trees/test-slug",
        next_call="telec todo work test-slug",
    )
    assert "Call telec todo work test-slug" in result
    assert "Call telec todo work test-slug()" not in result


# =============================================================================
# Build Gate Tests (preserved from original)
# =============================================================================

import subprocess
import time

from unittest.mock import AsyncMock

from teleclaude.core.next_machine import next_work
from teleclaude.core.next_machine.core import POST_COMPLETION, _get_slug_single_flight_lock, format_build_gate_failure


def _write_roadmap_yaml(tmpdir: str, slugs: list[str]) -> None:
    """Helper to write a roadmap.yaml with given slugs."""
    import yaml as _yaml

    roadmap_path = Path(tmpdir) / "todos" / "roadmap.yaml"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"slug": s} for s in slugs]
    roadmap_path.write_text(_yaml.dump(entries, default_flow_style=False))


@pytest.mark.asyncio
async def test_next_work_runs_gates_when_build_complete():
    """next_work runs build gates when build is complete, passing gates lead to review."""
    db = MagicMock(spec=Db)
    slug = "gate-test"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "GATE PASSED: all")),
            patch("teleclaude.core.next_machine.core.verify_artifacts", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review-build" in result


@pytest.mark.asyncio
async def test_next_work_gate_failure_resets_build():
    """Failing gates reset build to started and return gate-failure instruction."""
    db = MagicMock(spec=Db)
    slug = "gate-fail"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        gate_output = "GATE FAILED: make test (exit 1)\nTest output..."

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(False, gate_output)),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "BUILD GATES FAILED" in result
        assert "GATE FAILED" in result
        assert "Test output" in result

        state = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert state["build"] == "started"


@pytest.mark.asyncio
async def test_next_work_gate_failure_includes_output():
    """Gate failure response includes failure output for the builder."""
    db = MagicMock(spec=Db)
    slug = "gate-output"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        gate_output = "GATE FAILED: demo validate (exit 1)\nno executable bash blocks"

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(False, gate_output)),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "demo validate" in result
        assert "no executable bash blocks" in result
        assert "Send" in result


@pytest.mark.asyncio
async def test_next_work_lazy_marking_no_state_mutation():
    """next_work does NOT mutate build state when returning a new build dispatch."""
    db = MagicMock(spec=Db)
    slug = "lazy-mark"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "phase": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-build" in result

        state = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert state["build"] == "pending"

        assert "mark-phase" in result
        assert "BEFORE DISPATCHING" in result


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_next_work_concurrent_same_slug_single_flight_prep():
    """Concurrent same-slug calls should run expensive prep at most once."""
    db = MagicMock(spec=Db)
    slug = "single-flight"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"], cwd=tmpdir, check=True, capture_output=True, text=True
        )
        subprocess.run(["git", "config", "user.name", "Tests"], cwd=tmpdir, check=True, capture_output=True, text=True)

        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = tmp_path / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        subprocess.run(["git", "add", "todos"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "worktree", "add", f"trees/{slug}", "-b", slug],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        )

        worktree_todo = tmp_path / "trees" / slug / "todos" / slug
        (worktree_todo / "state.yaml").write_text('{"build":"pending","review":"pending"}')

        prep_calls = 0

        def _slow_prepare(*_args: object, **_kwargs: object) -> None:
            nonlocal prep_calls
            prep_calls += 1
            time.sleep(0.1)

        with (
            patch("teleclaude.core.next_machine.core._prepare_worktree", side_effect=_slow_prepare),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result_a, result_b = await asyncio.gather(
                next_work(db, slug=slug, cwd=tmpdir),
                next_work(db, slug=slug, cwd=tmpdir),
            )

        assert "next-build" in result_a
        assert "next-build" in result_b
        assert prep_calls == 1
        assert (tmp_path / "trees" / slug / ".teleclaude" / "worktree-prep-state.json").exists()


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_next_work_concurrent_same_slug_different_repos_do_not_serialize_prep():
    """Same slug in separate repos should not block each other's prep phase."""
    db = MagicMock(spec=Db)
    slug = "same-slug"

    def _init_repo(root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True, capture_output=True, text=True)
        _write_roadmap_yaml(str(root), [slug])

        item_dir = root / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        subprocess.run(["git", "add", "todos"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "worktree", "add", f"trees/{slug}", "-b", slug],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        (root / "trees" / slug / "todos" / slug / "state.yaml").write_text('{"build":"pending","review":"pending"}')

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir(parents=True, exist_ok=True)
        repo_b.mkdir(parents=True, exist_ok=True)
        _init_repo(repo_a)
        _init_repo(repo_b)

        lock_a = await _get_slug_single_flight_lock(str(repo_a), slug)
        lock_b = await _get_slug_single_flight_lock(str(repo_b), slug)
        assert lock_a is not lock_b

        prep_calls = 0

        def _slow_prepare(*_args: object, **_kwargs: object) -> None:
            nonlocal prep_calls
            prep_calls += 1
            time.sleep(0.1)

        with (
            patch("teleclaude.core.next_machine.core._prepare_worktree", side_effect=_slow_prepare),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="guidance"),
            ),
        ):
            result_a, result_b = await asyncio.gather(
                next_work(db, slug=slug, cwd=str(repo_a)),
                next_work(db, slug=slug, cwd=str(repo_b)),
            )

        assert "next-build" in result_a
        assert "next-build" in result_b
        assert prep_calls == 2
        assert (repo_a / "trees" / slug / ".teleclaude" / "worktree-prep-state.json").exists()
        assert (repo_b / "trees" / slug / ".teleclaude" / "worktree-prep-state.json").exists()


@pytest.mark.asyncio
async def test_next_work_single_flight_is_scoped_to_repo_and_slug():
    """Same slug should serialize per repo, not across different repos."""
    slug = "same-slug"
    repo_a = "/tmp/repo-a"
    repo_b = "/tmp/repo-b"

    lock_a_first = await _get_slug_single_flight_lock(repo_a, slug)
    lock_a_second = await _get_slug_single_flight_lock(repo_a, slug)
    lock_b = await _get_slug_single_flight_lock(repo_b, slug)

    assert lock_a_first is lock_a_second
    assert lock_a_first is not lock_b

    hold_ready = asyncio.Event()
    release_hold = asyncio.Event()

    async def _hold_repo_a_lock() -> None:
        async with lock_a_first:
            hold_ready.set()
            await release_hold.wait()

    hold_task = asyncio.create_task(_hold_repo_a_lock())
    await hold_ready.wait()

    same_repo_waiter = asyncio.create_task(lock_a_second.acquire())
    await asyncio.sleep(0)
    assert same_repo_waiter.done() is False

    acquired_other_repo = await asyncio.wait_for(lock_b.acquire(), timeout=0.2)
    assert acquired_other_repo is True
    lock_b.release()

    release_hold.set()
    await hold_task
    await same_repo_waiter
    lock_a_second.release()


def test_post_completion_finalize_hands_off_to_integrator():
    """POST_COMPLETION for next-finalize records finalize-ready, then reruns the slug for handoff."""
    instructions = POST_COMPLETION["next-finalize"]
    assert "FINALIZE_READY: {args}" in instructions
    assert "<session_id>" in instructions
    assert "telec todo mark-finalize-ready {args} --worker-session-id <session_id>" in instructions
    assert "Call {next_call}" in instructions
    assert "telec todo integrate" not in instructions
    # Lock mechanism is gone — integrator handles serialization via its own lease
    assert "todos/.finalize-lock" not in instructions
    assert "TELECLAUDE_SESSION_ID" not in instructions
    assert "make restart" not in instructions
    assert "FINALIZE APPLY SAFETY RE-CHECK" not in instructions
    assert "git push origin main" not in instructions


def test_format_build_gate_failure_structure():
    """format_build_gate_failure produces correct instruction structure."""
    result = format_build_gate_failure("test-slug", "GATE FAILED: make test", "telec todo work")
    assert "BUILD GATES FAILED: test-slug" in result
    assert "GATE FAILED: make test" in result
    assert "Send" in result
    assert "Do NOT end" in result
    assert "mark-phase" in result


# =============================================================================
# Freshness Gate Tests (R9) — next_work
# =============================================================================


@pytest.mark.asyncio
async def test_next_work_freshness_gate_blocks_non_prepared_phase():
    """next_work returns STALE when prepare_phase is set to a non-'prepared' value."""
    db = MagicMock(spec=Db)
    slug = "stale-feature"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        # prepare_phase is "discovery" — preparation not yet complete
        (item_dir / "state.yaml").write_text(
            yaml.dump({"phase": "in_progress", "dor": {"score": 9}, "prepare_phase": "discovery"})
        )

        with (
            patch("teleclaude.core.next_machine.core.resolve_canonical_project_root", return_value=tmpdir),
            patch("teleclaude.core.next_machine.core.sweep_completed_groups"),
            patch("teleclaude.core.next_machine.core.load_roadmap_deps", return_value={}),
            patch("teleclaude.core.next_machine.core.is_bug_todo", return_value=False),
            patch("teleclaude.core.next_machine.core.get_item_phase", return_value="in_progress"),
            patch("teleclaude.core.next_machine.core.check_dependencies_satisfied", return_value=True),
            patch("teleclaude.core.next_machine.core.get_stash_entries", return_value=[]),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

    assert "STALE" in result
    assert "discovery" in result


@pytest.mark.asyncio
async def test_next_work_freshness_gate_blocks_invalidated_grounding():
    """next_work returns STALE when prepare_phase is 'prepared' but grounding.valid is false."""
    db = MagicMock(spec=Db)
    slug = "stale-grounding"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n")
        (item_dir / "implementation-plan.md").write_text("# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n")
        # prepare_phase is "prepared" but grounding was invalidated
        (item_dir / "state.yaml").write_text(
            yaml.dump(
                {
                    "phase": "in_progress",
                    "dor": {"score": 9},
                    "prepare_phase": "prepared",
                    "grounding": {
                        "valid": False,
                        "base_sha": "abc123",
                        "input_digest": "old",
                        "referenced_paths": ["src/foo.py"],
                        "last_grounded_at": "2026-01-01T00:00:00+00:00",
                        "invalidated_at": "2026-02-01T00:00:00+00:00",
                        "invalidation_reason": "files_changed",
                    },
                }
            )
        )

        with (
            patch("teleclaude.core.next_machine.core.resolve_canonical_project_root", return_value=tmpdir),
            patch("teleclaude.core.next_machine.core.sweep_completed_groups"),
            patch("teleclaude.core.next_machine.core.load_roadmap_deps", return_value={}),
            patch("teleclaude.core.next_machine.core.is_bug_todo", return_value=False),
            patch("teleclaude.core.next_machine.core.get_item_phase", return_value="in_progress"),
            patch("teleclaude.core.next_machine.core.check_dependencies_satisfied", return_value=True),
            patch("teleclaude.core.next_machine.core.get_stash_entries", return_value=[]),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

    assert "STALE" in result
    assert "grounding.valid=false" in result


# =============================================================================
# BLOCKED Terminal State Tests (I3) — next_prepare
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_blocked_terminal_emits_event_and_returns_message():
    """BLOCKED phase returns terminal BLOCKED message and emits prepare.blocked event."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    state = {
        "prepare_phase": PreparePhase.BLOCKED.value,
        "grounding": {
            "valid": False,
            "base_sha": "abc",
            "input_digest": "",
            "referenced_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "2026-01-01T00:00:00+00:00",
            "invalidation_reason": "max_review_rounds_exceeded",
        },
    }

    emitted: list[str] = []

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch(
            "teleclaude.core.next_machine.core._emit_prepare_event",
            side_effect=lambda et, _: emitted.append(et),
        ),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)

    assert "BLOCKED" in result
    assert slug in result
    assert "domain.software-development.prepare.blocked" in emitted


# =============================================================================
# No-Verdict Dispatch Tests (I4) — next_prepare
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_requirements_review_empty_verdict_dispatches_reviewer():
    """REQUIREMENTS_REVIEW with empty verdict dispatches next-review-requirements."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.REQUIREMENTS_REVIEW.value,
        "requirements_review": {"verdict": "", "reviewed_at": "", "findings_count": 0},
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)

    assert "next-review-requirements" in result
    assert slug in result


@pytest.mark.asyncio
async def test_prepare_plan_review_empty_verdict_dispatches_reviewer():
    """PLAN_REVIEW with empty verdict dispatches next-review-plan."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.PLAN_REVIEW.value,
        "plan_review": {"verdict": "", "reviewed_at": "", "findings_count": 0},
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)

    assert "next-review-plan" in result
    assert slug in result


# =============================================================================
# Input Drift Detection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_input_drift_reroutes_to_discovery():
    """Input digest change at machine entry resets phase to DISCOVERY."""
    db = MagicMock(spec=Db)
    slug = "drift-slug"

    with tempfile.TemporaryDirectory() as tmpdir:
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True)
        (item_dir / "input.md").write_text("updated input content")
        old_digest = hashlib.sha256(b"original input content").hexdigest()

        initial_state = {
            **{k: v for k, v in read_phase_state(tmpdir, slug).items()},
            "prepare_phase": PreparePhase.PLAN_REVIEW.value,
            "grounding": {
                "valid": True,
                "base_sha": "abc",
                "input_digest": old_digest,
                "referenced_paths": [],
                "last_grounded_at": "",
                "invalidated_at": "",
                "invalidation_reason": "",
            },
            "requirements_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0, "rounds": 1},
            "plan_review": {"verdict": "needs_work", "reviewed_at": "", "findings_count": 1, "rounds": 1},
        }

        write_phase_state(tmpdir, slug, initial_state)

        db.clear_expired_agent_availability.return_value = None
        db.get_agent_availability.return_value = {"available": True}

        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=tmpdir)

        assert "next-prepare-discovery" in result
        reloaded = read_phase_state(tmpdir, slug)
        assert reloaded["prepare_phase"] == PreparePhase.DISCOVERY.value
        req_review = reloaded.get("requirements_review", {})
        assert isinstance(req_review, dict) and req_review.get("verdict") == ""
        plan_review = reloaded.get("plan_review", {})
        assert isinstance(plan_review, dict) and plan_review.get("verdict") == ""


# =============================================================================
# RE_GROUNDING Cascade Tests
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_regrounding_input_updated_dispatches_discovery():
    """RE_GROUNDING with input_updated reason dispatches discovery, not draft."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    state = {
        "prepare_phase": PreparePhase.RE_GROUNDING.value,
        "grounding": {
            "valid": False,
            "base_sha": "abc",
            "input_digest": "old",
            "referenced_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "2026-01-01T00:00:00+00:00",
            "invalidation_reason": "input_updated",
            "changed_paths": [],
        },
        "requirements_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0, "rounds": 0},
        "plan_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0, "rounds": 0},
    }

    written_state = {}

    def fake_write(_cwd, _slug, s):
        written_state.update(s)

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core.write_phase_state", side_effect=fake_write),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)

    assert "next-prepare-discovery" in result
    assert written_state.get("prepare_phase") == PreparePhase.DISCOVERY.value
    req_review = written_state.get("requirements_review", {})
    assert isinstance(req_review, dict) and req_review.get("verdict") == ""


# =============================================================================
# Fix Mode Note Tests
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_needs_work_note_contains_fix_mode():
    """needs_work dispatches contain 'FIX MODE' in the note for both review types."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "fix-mode-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    # Test requirements review needs_work → FIX MODE
    req_state = {
        "prepare_phase": PreparePhase.REQUIREMENTS_REVIEW.value,
        "requirements_review": {"verdict": "needs_work", "reviewed_at": "", "findings_count": 1, "rounds": 0},
    }
    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=req_state),
        patch("teleclaude.core.next_machine.core.write_phase_state"),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)
    assert "FIX MODE" in result

    # Test plan review needs_work → FIX MODE
    plan_state = {
        "prepare_phase": PreparePhase.PLAN_REVIEW.value,
        "plan_review": {"verdict": "needs_work", "reviewed_at": "", "findings_count": 1, "rounds": 0},
    }
    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=plan_state),
        patch("teleclaude.core.next_machine.core.write_phase_state"),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=True),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result2 = await next_prepare(db, slug=slug, cwd=cwd)
    assert "FIX MODE" in result2


# =============================================================================
# Block Reason Persistence Tests
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_blocked_stores_reason():
    """BLOCKED state reads blocked_reason from state, not grounding."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "blocked-reason-slug"

    state = {
        "prepare_phase": PreparePhase.BLOCKED.value,
        "blocked_reason": "requirements review exceeded 3 rounds",
        "grounding": {
            "valid": False,
            "base_sha": "",
            "input_digest": "",
            "referenced_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "",
            "invalidation_reason": "",
        },
    }

    with (
        patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
        patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
        patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.core._emit_prepare_event"),
    ):
        result = await next_prepare(db, slug=slug, cwd=cwd)

    assert "BLOCKED" in result
    assert "requirements review exceeded 3 rounds" in result


# =============================================================================
# Legacy Phase Name Migration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_prepare_legacy_phase_names_map_to_discovery():
    """Legacy phase names 'input_assessment' and 'triangulation' map to DISCOVERY."""
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "legacy-slug"
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    for legacy_name in ("input_assessment", "triangulation"):
        state = {
            "prepare_phase": legacy_name,
        }
        with (
            patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]),
            patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True),
            patch("teleclaude.core.next_machine.core.read_phase_state", return_value=state),
            patch("teleclaude.core.next_machine.core.write_phase_state"),
            patch("teleclaude.core.next_machine.core.check_file_exists", return_value=False),
        patch("teleclaude.core.next_machine.core.check_file_has_content", return_value=False),
            patch("teleclaude.core.next_machine.core._emit_prepare_event"),
        ):
            result = await next_prepare(db, slug=slug, cwd=cwd)
        assert "next-prepare-discovery" in result, f"Failed for legacy name: {legacy_name}"

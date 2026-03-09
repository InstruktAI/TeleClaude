"""Tests for PreparePhase enum, state schema, and invalidation check."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from teleclaude.core.next_machine.core import (
    DEFAULT_STATE,
    PreparePhase,
    _PREPARE_LOOP_LIMIT,
    invalidate_stale_preparations,
    read_phase_state,
    write_phase_state,
)


# =============================================================================
# Enum validation
# =============================================================================


def test_prepare_phase_has_all_9_values():
    """PreparePhase enum defines exactly 9 states."""
    assert len(list(PreparePhase)) == 9


def test_prepare_phase_values_are_string_typed():
    """All PreparePhase values are strings."""
    for phase in PreparePhase:
        assert isinstance(phase.value, str), f"{phase.name} value is not a string"


def test_prepare_phase_expected_values():
    """PreparePhase enum contains all expected state names."""
    expected = {
        "discovery",
        "requirements_review",
        "plan_drafting",
        "plan_review",
        "gate",
        "grounding_check",
        "re_grounding",
        "prepared",
        "blocked",
    }
    actual = {phase.value for phase in PreparePhase}
    assert actual == expected


def test_prepare_loop_limit_positive():
    """_PREPARE_LOOP_LIMIT is a positive integer."""
    assert isinstance(_PREPARE_LOOP_LIMIT, int)
    assert _PREPARE_LOOP_LIMIT > 0


def test_prepare_phase_from_string():
    """PreparePhase can be constructed from a string value."""
    phase = PreparePhase("prepared")
    assert phase == PreparePhase.PREPARED

    phase2 = PreparePhase("blocked")
    assert phase2 == PreparePhase.BLOCKED


def test_prepare_phase_invalid_raises():
    """PreparePhase raises ValueError for unknown phase string."""
    with pytest.raises(ValueError):
        PreparePhase("unknown_phase")


# =============================================================================
# DEFAULT_STATE schema
# =============================================================================


def test_default_state_has_prepare_phase_key():
    """DEFAULT_STATE includes prepare_phase key initialized to empty string."""
    assert "prepare_phase" in DEFAULT_STATE
    assert DEFAULT_STATE["prepare_phase"] == ""


def test_default_state_has_blocked_reason():
    """DEFAULT_STATE includes blocked_reason key initialized to empty string."""
    assert "blocked_reason" in DEFAULT_STATE
    assert DEFAULT_STATE["blocked_reason"] == ""


def test_default_state_has_grounding_section():
    """DEFAULT_STATE includes grounding section with all required sub-keys."""
    grounding = DEFAULT_STATE["grounding"]
    assert isinstance(grounding, dict)
    assert grounding["valid"] is False
    assert grounding["base_sha"] == ""
    assert grounding["input_digest"] == ""
    assert grounding["referenced_paths"] == []
    assert grounding["last_grounded_at"] == ""
    assert grounding["invalidated_at"] == ""
    assert grounding["invalidation_reason"] == ""


def test_default_state_has_requirements_review_section():
    """DEFAULT_STATE includes requirements_review section."""
    rr = DEFAULT_STATE["requirements_review"]
    assert isinstance(rr, dict)
    assert rr["verdict"] == ""
    assert rr["reviewed_at"] == ""
    assert rr["findings_count"] == 0


def test_default_state_has_plan_review_section():
    """DEFAULT_STATE includes plan_review section."""
    pr = DEFAULT_STATE["plan_review"]
    assert isinstance(pr, dict)
    assert pr["verdict"] == ""
    assert pr["reviewed_at"] == ""
    assert pr["findings_count"] == 0


# =============================================================================
# State I/O round-trip
# =============================================================================


def test_state_round_trip_with_all_new_sections():
    """Write extended state with all new sections; read back and verify preservation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "test-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)

        original = {
            "build": "pending",
            "review": "pending",
            "prepare_phase": "grounding_check",
            "grounding": {
                "valid": True,
                "base_sha": "abc123",
                "input_digest": "deadbeef",
                "referenced_paths": ["src/foo.py"],
                "last_grounded_at": "2026-01-01T00:00:00+00:00",
                "invalidated_at": "",
                "invalidation_reason": "",
            },
            "requirements_review": {
                "verdict": "approve",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "findings_count": 0,
            },
            "plan_review": {
                "verdict": "approve",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "findings_count": 1,
            },
        }

        with patch("teleclaude.core.next_machine.core.Repo"):
            write_phase_state(tmpdir, slug, original)

        loaded = read_phase_state(tmpdir, slug)

        assert loaded["prepare_phase"] == "grounding_check"
        assert isinstance(loaded["grounding"], dict)
        grounding = loaded["grounding"]
        assert grounding["valid"] is True
        assert grounding["base_sha"] == "abc123"
        assert grounding["input_digest"] == "deadbeef"
        assert grounding["referenced_paths"] == ["src/foo.py"]

        rr = loaded["requirements_review"]
        assert isinstance(rr, dict)
        assert rr["verdict"] == "approve"
        assert rr["findings_count"] == 0

        pr = loaded["plan_review"]
        assert isinstance(pr, dict)
        assert pr["verdict"] == "approve"
        assert pr["findings_count"] == 1


def test_backward_compat_state_without_new_sections():
    """Legacy state.yaml without new sections loads with sensible defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "legacy-slug"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)
        (state_dir / "state.yaml").write_text(yaml.dump({"build": "complete", "review": "pending"}))

        state = read_phase_state(tmpdir, slug)

        assert state["prepare_phase"] == ""
        grounding = state["grounding"]
        assert isinstance(grounding, dict)
        assert grounding["valid"] is False
        assert grounding["base_sha"] == ""
        rr = state["requirements_review"]
        assert isinstance(rr, dict)
        assert rr["verdict"] == ""
        pr = state["plan_review"]
        assert isinstance(pr, dict)
        assert pr["verdict"] == ""
        # Legacy fields preserved
        assert state["build"] == "complete"
        assert state["review"] == "pending"


def test_existing_hitl_tests_for_state_pass():
    """read_phase_state returns default with new keys in addition to original keys."""
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
        # New keys
        assert state["prepare_phase"] == ""
        assert isinstance(state["grounding"], dict)
        assert isinstance(state["requirements_review"], dict)
        assert isinstance(state["plan_review"], dict)


# =============================================================================
# invalidate_stale_preparations
# =============================================================================


def test_invalidate_stale_preparations_marks_overlapping_todos():
    """invalidate_stale_preparations marks todos whose referenced paths overlap."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-feature"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)

        roadmap_path = Path(tmpdir) / "todos" / "roadmap.yaml"
        roadmap_path.write_text(yaml.dump([{"slug": slug}]))

        (state_dir / "state.yaml").write_text(
            yaml.dump(
                {
                    "prepare_phase": "prepared",
                    "grounding": {
                        "valid": True,
                        "base_sha": "abc",
                        "input_digest": "",
                        "referenced_paths": ["src/foo.py", "src/bar.py"],
                        "last_grounded_at": "",
                        "invalidated_at": "",
                        "invalidation_reason": "",
                    },
                }
            )
        )

        with patch("teleclaude.core.next_machine.core._emit_prepare_event"):
            result = invalidate_stale_preparations(tmpdir, ["src/foo.py"])

        assert slug in result["invalidated"]

        loaded = read_phase_state(tmpdir, slug)
        grounding = loaded["grounding"]
        assert isinstance(grounding, dict)
        assert grounding["valid"] is False
        assert grounding["invalidation_reason"] == "files_changed"
        assert grounding["invalidated_at"] != ""
        # C1 regression guard: invalidation must reset prepare_phase to grounding_check
        assert loaded["prepare_phase"] == "grounding_check"


def test_invalidate_stale_preparations_ignores_non_overlapping():
    """invalidate_stale_preparations does not touch todos with no path overlap."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "unrelated-feature"
        state_dir = Path(tmpdir) / "todos" / slug
        state_dir.mkdir(parents=True)

        roadmap_path = Path(tmpdir) / "todos" / "roadmap.yaml"
        roadmap_path.write_text(yaml.dump([{"slug": slug}]))

        (state_dir / "state.yaml").write_text(
            yaml.dump(
                {
                    "grounding": {
                        "valid": True,
                        "base_sha": "abc",
                        "input_digest": "",
                        "referenced_paths": ["src/other.py"],
                        "last_grounded_at": "",
                        "invalidated_at": "",
                        "invalidation_reason": "",
                    }
                }
            )
        )

        with patch("teleclaude.core.next_machine.core._emit_prepare_event") as mock_emit:
            result = invalidate_stale_preparations(tmpdir, ["src/unrelated.py"])

        assert result["invalidated"] == []
        mock_emit.assert_not_called()

        loaded = read_phase_state(tmpdir, slug)
        grounding = loaded["grounding"]
        assert isinstance(grounding, dict)
        assert grounding["valid"] is True


def test_invalidate_stale_preparations_emits_event_per_slug():
    """invalidate_stale_preparations emits grounding_invalidated event for each invalidated slug."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slugs = ["feat-a", "feat-b"]
        roadmap_entries = [{"slug": s} for s in slugs]
        todos_dir = Path(tmpdir) / "todos"
        todos_dir.mkdir(parents=True, exist_ok=True)
        (todos_dir / "roadmap.yaml").write_text(yaml.dump(roadmap_entries))

        for slug in slugs:
            state_dir = Path(tmpdir) / "todos" / slug
            state_dir.mkdir(parents=True)
            (state_dir / "state.yaml").write_text(
                yaml.dump(
                    {
                        "grounding": {
                            "valid": True,
                            "base_sha": "abc",
                            "input_digest": "",
                            "referenced_paths": ["shared/module.py"],
                            "last_grounded_at": "",
                            "invalidated_at": "",
                            "invalidation_reason": "",
                        }
                    }
                )
            )

        emitted: list[str] = []
        with patch(
            "teleclaude.core.next_machine.core._emit_prepare_event",
            side_effect=lambda et, _: emitted.append(et),
        ):
            result = invalidate_stale_preparations(tmpdir, ["shared/module.py"])

        assert set(result["invalidated"]) == {"feat-a", "feat-b"}
        assert emitted.count("domain.software-development.prepare.grounding_invalidated") == 2

"""Tests for Task 3: artifact staleness wiring in next_prepare dispatch loop
and record_input_consumed emission at input_assessment → requirements_review transition.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    return str(tmp_path), slug


def _write_file(todo_dir: Path, name: str, content: str = "content") -> Path:
    p = todo_dir / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# check_artifact_staleness integration with next_prepare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.prepare._emit_prepare_event")
@patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event")
async def test_next_prepare_staleness_triggers_artifact_invalidated(
    mock_helpers_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Modifying input.md after recording triggers cascade and emits artifact_invalidated."""
    from teleclaude.core.next_machine.core import next_prepare, write_phase_state
    from teleclaude.core.next_machine.prepare_helpers import record_artifact_produced

    cwd, slug = _make_todo(tmp_path)
    long_content = "This is the original content that is long enough to pass the scaffold content check in teleclaude."
    input_file = _write_file(tmp_path / "todos" / slug, "input.md", long_content)
    _write_file(tmp_path / "todos" / slug, "requirements.md", "Requirements document with enough content to pass scaffold threshold for testing purposes.")

    # Record input artifact
    record_artifact_produced(cwd, slug, "input.md")

    # Also record requirements so the machine has lifecycle data for both
    record_artifact_produced(cwd, slug, "requirements.md")

    # Write state saying we're at requirements_review with approve — so machine
    # would normally advance, but artifact invalidation should intercept first
    from teleclaude.core.next_machine.core import read_phase_state

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "requirements_review"
    state["requirements_review"] = {  # type: ignore[assignment]
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    write_phase_state(cwd, slug, state)

    # Modify input.md to trigger staleness
    input_file.write_text("changed content")

    mock_db = MagicMock()
    mock_db.scalar_one_or_none = AsyncMock(return_value=None)

    with patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        with patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    # artifact_invalidated should have been emitted
    all_calls = [c[0][0] for c in mock_core_emit.call_args_list] + [c[0][0] for c in mock_helpers_emit.call_args_list]
    assert any("artifact_invalidated" in call for call in all_calls), f"Expected artifact_invalidated in {all_calls}"


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.prepare._emit_prepare_event")
@patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event")
async def test_next_prepare_no_staleness_proceeds_normally(
    mock_helpers_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """When no artifacts are stale, phase routing proceeds normally without extra context."""
    from teleclaude.core.next_machine.core import next_prepare, write_phase_state
    from teleclaude.core.next_machine.prepare_helpers import record_artifact_produced

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md", "This is stable input that has enough content to pass scaffold threshold for the test.")

    # Record input artifact — no changes after
    record_artifact_produced(cwd, slug, "input.md")

    # State: input_assessment with no requirements yet
    from teleclaude.core.next_machine.core import read_phase_state

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "input_assessment"
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        with patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    # Should have dispatched discovery (no staleness)
    all_calls = [c[0][0] for c in mock_core_emit.call_args_list]
    assert not any("artifact_invalidated" in call for call in all_calls)
    # Result is a dispatch instruction (not blocked/errored)
    assert "DISPATCH" in result or "next-prepare-discovery" in result



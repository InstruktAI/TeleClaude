"""Tests for Task 11: referenced path existence check after plan drafting."""

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


def _write_file(path: Path, name: str, content: str = "content long enough to pass check threshold here") -> Path:
    p = path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.prepare._emit_prepare_event")
async def test_plan_with_missing_referenced_paths_returns_redraft(
    _mock_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """When plan references non-existent paths, machine returns re-draft instead of advancing to plan review."""
    from teleclaude.core.next_machine.core import (
        next_prepare,
        read_phase_state,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")

    # Write a plan with content
    plan_content = "Implementation plan with enough content to pass the scaffold threshold check here."
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md", plan_content)

    # State: plan_drafting with referenced_paths pointing to non-existent files
    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "plan_drafting"
    state["requirements_review"] = {  # type: ignore[assignment]
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    state["grounding"] = {  # type: ignore[assignment]
        "valid": True,
        "base_sha": "abc123",
        "input_digest": "",
        "referenced_paths": [
            "teleclaude/nonexistent_module.py",  # does not exist
            "teleclaude/core/next_machine/core.py",  # exists
        ],
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    }
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        with patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    # Should return a re-draft instruction (not loop to plan_review)
    assert "next-prepare-draft" in result or "DISPATCH" in result
    # Missing path should appear in the output
    assert "nonexistent_module.py" in result


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.prepare._emit_prepare_event")
async def test_plan_with_valid_referenced_paths_advances_to_plan_review(
    _mock_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """When all referenced paths exist, machine advances to plan review normally."""
    from teleclaude.core.next_machine.core import (
        next_prepare,
        read_phase_state,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")

    # Write plan with content
    plan_content = "Implementation plan with enough content to pass the scaffold threshold check here."
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md", plan_content)

    # Create a real file to reference
    (tmp_path / "teleclaude").mkdir(exist_ok=True)
    _write_file(tmp_path / "teleclaude", "real_file.py", "# real python file")

    # State: plan_drafting with all referenced_paths existing
    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "plan_drafting"
    state["requirements_review"] = {  # type: ignore[assignment]
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    state["grounding"] = {  # type: ignore[assignment]
        "valid": True,
        "base_sha": "abc123",
        "input_digest": "",
        "referenced_paths": ["teleclaude/real_file.py"],  # exists
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    }
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        with patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    # Should dispatch a reviewer (advanced past plan_drafting to plan_review)
    assert "next-review-plan" in result or "DISPATCH" in result or "plan_review" in result.lower()
    # Missing paths message must NOT appear
    assert "nonexistent" not in result


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.prepare._emit_prepare_event")
async def test_plan_with_empty_referenced_paths_advances_normally(
    _mock_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """When referenced_paths is empty, machine advances to plan review (no paths to validate)."""
    from teleclaude.core.next_machine.core import (
        next_prepare,
        read_phase_state,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")

    plan_content = "Implementation plan with enough content to pass the scaffold threshold check here."
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md", plan_content)

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "plan_drafting"
    state["requirements_review"] = {  # type: ignore[assignment]
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    state["grounding"] = {  # type: ignore[assignment]
        "valid": True,
        "base_sha": "abc123",
        "input_digest": "",
        "referenced_paths": [],  # empty — no paths to validate
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    }
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        with patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    # Should advance to plan review
    assert "next-review-plan" in result or "DISPATCH" in result or "plan_review" in result.lower()

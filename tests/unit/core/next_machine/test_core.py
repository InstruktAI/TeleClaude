"""Tests for teleclaude.core.next_machine.core — phase derivation, dispatch, verdicts, artifacts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from teleclaude.core.next_machine._types import StateValue

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LONG = "This content is long enough to pass the scaffold content threshold check for tests."


def _mock_todos_db() -> AsyncMock:
    """Mock TodosDb for core tests."""
    db = AsyncMock()
    db.write_state = AsyncMock()
    db.read_state = AsyncMock(return_value=None)
    db.artifact_digest = AsyncMock(return_value="")
    db.slug_in_roadmap = AsyncMock(return_value=True)
    db.add_to_roadmap = AsyncMock(return_value=True)
    return db


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    return str(tmp_path), slug


def _write_file(base: Path, name: str, content: str = _LONG) -> Path:
    p = base / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# is_bug_todo / verify_artifacts — bug route identity and artifact checks
# ---------------------------------------------------------------------------


class _git_result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _write_state(todo_dir: Path, state: dict) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.dump(state, default_flow_style=False), encoding="utf-8")


def test_bug_md_presence_does_not_determine_bug_identity(tmp_path: Path) -> None:
    """bug.md existing with kind='todo' must NOT make it a bug."""
    from teleclaude.core.next_machine.core import is_bug_todo

    todo_dir = tmp_path / "todos" / "add-feature"
    _write_state(todo_dir, {"kind": "todo", "build": "pending"})
    (todo_dir / "bug.md").write_text("misleading file", encoding="utf-8")

    assert is_bug_todo(str(tmp_path), "add-feature") is False


def test_bug_build_passes_without_implementation_plan_or_checklist(tmp_path: Path) -> None:
    """Bug build verification must pass with only bug.md and commits."""
    from teleclaude.core.next_machine.core import verify_artifacts

    todo_dir = tmp_path / "todos" / "fix-crash"
    _write_state(todo_dir, {"kind": "bug", "build": "complete"})
    (todo_dir / "bug.md").write_text("Real bug report content here.", encoding="utf-8")

    mock_repo = MagicMock()
    mock_repo.git.merge_base.return_value = "abc123"
    mock_repo.git.log.return_value = "abc123 fix the crash"

    with patch("teleclaude.core.next_machine.build_gates.Repo", return_value=mock_repo):
        passed, _ = verify_artifacts(str(tmp_path), "fix-crash", "build", is_bug=True)

    assert passed is True


def test_bug_review_passes_without_quality_checklist(tmp_path: Path) -> None:
    """Bug review verification must pass with only review-findings.md."""
    from teleclaude.core.next_machine.core import verify_artifacts

    todo_dir = tmp_path / "todos" / "fix-reviewed"
    _write_state(todo_dir, {"kind": "bug", "build": "complete", "review": "approved"})
    (todo_dir / "review-findings.md").write_text(
        "# Review Findings\n\n"
        "## Findings\n\n"
        "Code quality is solid. All edge cases handled correctly. "
        "No security concerns identified during the review process.\n\n"
        "## Verdict\n\n"
        "[x] APPROVE\n",
        encoding="utf-8",
    )

    passed, _ = verify_artifacts(str(tmp_path), "fix-reviewed", "review", is_bug=True)
    assert passed is True


# ---------------------------------------------------------------------------
# _prepare_step_requirements_review — severity-based verdict
# ---------------------------------------------------------------------------


def _build_review_state(findings: list[dict[str, StateValue]], verdict: str = "") -> dict[str, StateValue]:
    return {
        "schema_version": 2,
        "prepare_phase": "requirements_review",
        "artifacts": {
            "input": {"digest": "", "produced_at": "2025-01-01", "stale": False},
            "requirements": {"digest": "", "produced_at": "2025-01-01", "stale": False},
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
        "requirements_review": {
            "verdict": verdict,
            "reviewed_at": "",
            "findings_count": len(findings),
            "rounds": 0,
            "baseline_commit": "",
            "findings": findings,  # type: ignore[dict-item]
        },
        "plan_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "audit": {
            "input_assessment": {"started_at": "", "completed_at": ""},
            "triangulation": {"started_at": "", "completed_at": ""},
            "requirements_review": {
                "started_at": "",
                "completed_at": "",
                "baseline_commit": "",
                "verdict": "",
                "rounds": 0,
                "findings": [],
            },
            "plan_drafting": {"started_at": "", "completed_at": ""},
            "plan_review": {
                "started_at": "",
                "completed_at": "",
                "baseline_commit": "",
                "verdict": "",
                "rounds": 0,
                "findings": [],
            },
            "gate": {"started_at": "", "completed_at": ""},
        },
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


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_all_findings_resolved_yields_approve(mock_emit: MagicMock, tmp_path: Path) -> None:
    """All findings resolved (no open) → verdict APPROVE, transitions to PLAN_DRAFTING."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    findings = [
        {"id": "f1", "severity": "trivial", "summary": "formatting", "status": "resolved", "resolved_at": "2025-01-01"},
        {
            "id": "f2",
            "severity": "substantive",
            "summary": "coverage",
            "status": "resolved",
            "resolved_at": "2025-01-01",
        },
    ]
    state = _build_review_state(findings, verdict="approve")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    keep_going, instruction = await _prepare_step_requirements_review(mock_db, _mock_todos_db(), slug, cwd, state)

    assert keep_going is True
    assert instruction == ""


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_unresolved_substantive_yields_needs_work(mock_emit: MagicMock, tmp_path: Path) -> None:
    """Unresolved substantive finding → NEEDS_WORK, note includes count and file pointer."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    findings = [
        {"id": "f1", "severity": "substantive", "summary": "missing coverage", "status": "open"},
    ]
    state = _build_review_state(findings, verdict="needs_work")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        keep_going, instruction = await _prepare_step_requirements_review(mock_db, _mock_todos_db(), slug, cwd, state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_unresolved_architectural_yields_blocked(mock_emit: MagicMock, tmp_path: Path) -> None:
    """Unresolved architectural finding → NEEDS_DECISION, BLOCKED output."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    findings = [
        {"id": "f1", "severity": "architectural", "summary": "contract mismatch", "status": "open"},
    ]
    state = _build_review_state(findings, verdict="needs_decision")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    keep_going, instruction = await _prepare_step_requirements_review(mock_db, _mock_todos_db(), slug, cwd, state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_v1_state_no_findings_key_does_not_raise(mock_emit: MagicMock, tmp_path: Path) -> None:
    """v1 state without findings key must not raise KeyError."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    state: dict[str, StateValue] = {
        "schema_version": 1,
        "prepare_phase": "requirements_review",
        "requirements_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
        },
        "plan_review": {"verdict": "", "findings_count": 0, "rounds": 0},
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
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        keep_going, instruction = await _prepare_step_requirements_review(mock_db, _mock_todos_db(), slug, cwd, state)

    assert keep_going is False
    assert instruction


# ---------------------------------------------------------------------------
# next_prepare — plan drafting advances to plan review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_plan_with_referenced_paths_advances_to_plan_review(
    _mock_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Plan with referenced_paths (including not-yet-created files) advances to review."""
    from teleclaude.core.next_machine.core import (
        next_prepare,
        read_phase_state,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md")

    state = read_phase_state(cwd, slug)
    state["current"] = "plan_drafting"
    state["requirements_review"] = {
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    state["grounding"] = {
        "valid": True,
        "base_sha": "abc123",
        "input_digest": "",
        "referenced_paths": [
            "teleclaude/nonexistent_module.py",
            "teleclaude/core/next_machine/core.py",
        ],
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    }
    artifacts = state.get("artifacts", {})
    if isinstance(artifacts, dict):
        impl_plan = artifacts.get("implementation_plan", {})
        if isinstance(impl_plan, dict):
            impl_plan["produced_at"] = "2025-01-01T00:00:00+00:00"
            artifacts["implementation_plan"] = impl_plan
    state["artifacts"] = artifacts
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        with patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    assert result


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_plan_with_empty_referenced_paths_advances_normally(
    _mock_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """When referenced_paths is empty, machine advances to plan review."""
    from teleclaude.core.next_machine.core import (
        next_prepare,
        read_phase_state,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md")

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "plan_drafting"
    state["requirements_review"] = {
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    state["grounding"] = {
        "valid": True,
        "base_sha": "abc123",
        "input_digest": "",
        "referenced_paths": [],
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
        with patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    assert result


# ---------------------------------------------------------------------------
# next_prepare — artifact staleness wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event")
@patch("teleclaude.core.next_machine.prepare._emit_prepare_event")
async def test_next_prepare_staleness_triggers_artifact_invalidated(
    mock_prepare_emit: MagicMock,
    mock_helpers_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Modifying input.md after recording triggers cascade and emits artifact_invalidated."""
    from teleclaude.core.next_machine.artifacts import record_artifact_produced
    from teleclaude.core.next_machine.core import next_prepare, write_phase_state

    cwd, slug = _make_todo(tmp_path)
    long_content = "This is the original content that is long enough to pass the scaffold content check in teleclaude."
    input_file = _write_file(tmp_path / "todos" / slug, "input.md", long_content)
    _write_file(
        tmp_path / "todos" / slug,
        "requirements.md",
        "Requirements document with enough content to pass scaffold threshold for testing purposes.",
    )

    record_artifact_produced(cwd, slug, "input.md")
    record_artifact_produced(cwd, slug, "requirements.md")

    from teleclaude.core.next_machine.core import read_phase_state

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "requirements_review"
    state["requirements_review"] = {
        "verdict": "approve",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [],
    }
    write_phase_state(cwd, slug, state)

    input_file.write_text("changed content")

    mock_db = MagicMock()
    mock_db.scalar_one_or_none = AsyncMock(return_value=None)

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        with patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    all_calls = (
        [c[0][0] for c in mock_core_emit.call_args_list]
        + [c[0][0] for c in mock_helpers_emit.call_args_list]
        + [c[0][0] for c in mock_prepare_emit.call_args_list]
    )
    assert any("artifact_invalidated" in call for call in all_calls), f"Expected artifact_invalidated in {all_calls}"


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event")
async def test_next_prepare_no_staleness_proceeds_normally(
    mock_helpers_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """When no artifacts are stale, phase routing proceeds normally."""
    from teleclaude.core.next_machine.artifacts import record_artifact_produced
    from teleclaude.core.next_machine.core import next_prepare, write_phase_state

    cwd, slug = _make_todo(tmp_path)
    _write_file(
        tmp_path / "todos" / slug,
        "input.md",
        "This is stable input that has enough content to pass scaffold threshold for the test.",
    )

    record_artifact_produced(cwd, slug, "input.md")

    from teleclaude.core.next_machine.core import read_phase_state

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = "input_assessment"
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch(
        "teleclaude.core.next_machine.prepare_steps.compose_agent_guidance",
        new_callable=AsyncMock,
        return_value="guidance",
    ):
        with patch("teleclaude.core.next_machine.core.slug_in_roadmap", return_value=True):
            with patch("teleclaude.core.next_machine.core.resolve_holder_children", return_value=[]):
                result = await next_prepare(mock_db, slug, cwd)

    all_calls = [c[0][0] for c in mock_core_emit.call_args_list]
    assert not any("artifact_invalidated" in call for call in all_calls)
    assert result

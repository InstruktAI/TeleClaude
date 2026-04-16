# guard: no-companion
"""Test spec (xfail) for prepare-lifecycle-pair-model.

These tests define the behavioral contract for the pair-owned prepare
workflow. They stay xfail-marked until the builder removes the marker and
implements the new lifecycle.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from teleclaude.cli.telec.handlers.todo import _handle_todo_stamp
from teleclaude.cli.telec.surface import CLI_SURFACE
from teleclaude.cli.tui.widgets.todo_row import prepare_phase_label
from teleclaude.constants import SlashCommand
from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.core.next_machine.work_steps import _work_step_build_started
from teleclaude.resource_validation import validate_todo
from teleclaude.types.todos import DorState

pytestmark = [
    pytest.mark.unit,
    pytest.mark.timeout(10),
    pytest.mark.xfail(
        reason="spec: pair-model prepare lifecycle not implemented yet",
        strict=False,
    ),
]


def _mock_todos_db() -> AsyncMock:
    db = AsyncMock()
    db.slug_in_roadmap = AsyncMock(return_value=True)
    db.read_state = AsyncMock(return_value={"schema_version": 2, "history": []})
    db.artifact_exists = AsyncMock(return_value=True)
    db.artifact_digest = AsyncMock(return_value="")
    return db


def test_prepare_phase_enum_matches_pair_model_contract() -> None:
    assert {phase.value for phase in PreparePhase} == {
        "input_assessment",
        "pair_discovery",
        "requirements_produced",
        "pair_completion",
        "grounding_check",
        "re_grounding",
        "prepared",
        "blocked",
    }


@pytest.mark.asyncio
async def test_requirements_produced_phase_waits_for_human_continue() -> None:
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "requirements_produced",
        "history": [],
    }

    with patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance") as mock_guidance:
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            todos_db=_mock_todos_db(),
            slug="slug-a",
            cwd="/tmp/project",
            phase=PreparePhase("requirements_produced"),
            state=state,
        )

    assert keep_going is False
    assert instruction
    assert mock_guidance.await_count == 0


@pytest.mark.asyncio
async def test_next_prepare_routes_from_current_pair_phase_without_phase_derivation() -> None:
    dispatch = AsyncMock(return_value=(False, "PAIR ROUTED"))
    todos_db = AsyncMock()
    todos_db.slug_in_roadmap = AsyncMock(return_value=True)
    todos_db.read_state = AsyncMock(
        return_value={
            "schema_version": 2,
            "current": "requirements_produced",
            "history": [],
        }
    )

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_holder_children_db", return_value=[]),
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", return_value="/tmp/project"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch("teleclaude.core.next_machine.prepare.check_artifact_staleness_db", return_value=[]),
        patch("teleclaude.core.next_machine.prepare._prepare_dispatch", dispatch),
        patch(
            "teleclaude.core.next_machine.prepare.derive_prepare_phase",
            side_effect=AssertionError("phase derivation must not drive prepare routing"),
        ),
    ):
        result = await next_prepare(MagicMock(), "slug-a", "/tmp/project")

    assert result == "PAIR ROUTED"
    assert dispatch.await_args.kwargs["phase"] == PreparePhase("requirements_produced")


@pytest.mark.asyncio
async def test_pair_completion_is_pair_boundary_and_grounding_becomes_mechanical() -> None:
    with patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance") as mock_guidance:
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            todos_db=_mock_todos_db(),
            slug="slug-b",
            cwd="/tmp/project",
            phase=PreparePhase("pair_completion"),
            state={"schema_version": 2, "current": "pair_completion", "history": []},
        )

    assert keep_going is True
    assert instruction == ""
    assert mock_guidance.await_count == 0


def test_dor_state_uses_binary_gates_and_has_no_numeric_score_fields() -> None:
    fields = set(DorState.model_fields)

    assert {"gates", "complete"} <= fields
    assert "score" not in fields
    assert "status" not in fields


@pytest.mark.asyncio
async def test_work_step_build_started_accepts_binary_dor_completion_without_score(tmp_path: Path) -> None:
    with (
        patch("teleclaude.core.next_machine.work_steps._find_live_session_for_slug", return_value=None),
        patch("teleclaude.core.next_machine.work_steps.compose_agent_guidance", return_value="guidance"),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=AsyncMock(),
            todos_db=AsyncMock(),
            slug="slug-c",
            cwd=str(tmp_path),
            worktree_cwd=str(tmp_path),
            state={"kind": "todo", "dor": {"complete": True}},
        )

    assert keep_going is False
    assert SlashCommand.NEXT_BUILD.value in instruction


def test_validate_todo_ready_contract_uses_binary_dor_complete(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-d"
    todo_dir.mkdir(parents=True)
    (todo_dir / "state.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "phase": "pending",
                "current": "pair_completion",
                "dor": {
                    "complete": True,
                    "gates": {
                        "intent_and_success": {"status": "pass"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (todo_dir / "implementation-plan.md").write_text("plan\n", encoding="utf-8")

    errors = validate_todo("slug-d", tmp_path)

    assert any("missing requirements.md" in err for err in errors)


def test_todo_stamp_surface_and_handler_drop_dor_score() -> None:
    stamp_def = CLI_SURFACE["todo"].subcommands["stamp"]
    assert "--dor-score" not in {flag.long for flag in stamp_def.visible_flags}

    with patch("teleclaude.cli.telec.handlers.todo.tool_api_request") as mock_api:
        with pytest.raises(SystemExit):
            _handle_todo_stamp(["my-slug", "--dor-score", "8"])

    mock_api.assert_not_called()


def test_prepare_phase_label_supports_pair_and_mechanical_states() -> None:
    assert prepare_phase_label("pair_discovery") is not None
    assert prepare_phase_label("requirements_produced") is not None
    assert prepare_phase_label("pair_completion") is not None
    assert prepare_phase_label("grounding_check") is not None
    assert prepare_phase_label("re_grounding") is not None
    assert prepare_phase_label("requirements_review") is None


@pytest.mark.asyncio
async def test_re_grounding_messages_live_pair_before_cold_fallback() -> None:
    # Import is deferred: prepare_scripts.py does not yet exist.
    from teleclaude.core.next_machine.prepare_scripts import (  # type: ignore[import-not-found]
        _handle_stale_grounding,
    )

    changed = ["teleclaude/core/foo.py"]

    # Live pair alive: relay changed-file context to it, skip cold-worker dispatch
    with (
        patch(
            "teleclaude.core.next_machine.prepare_scripts._find_live_session_for_slug",
            return_value="sess-live-abc",
        ),
        patch("teleclaude.core.next_machine.prepare_scripts.compose_agent_guidance") as mock_guidance,
    ):
        _, instruction_a = await _handle_stale_grounding(
            db=AsyncMock(),
            todos_db=_mock_todos_db(),
            slug="slug-rg",
            cwd="/tmp/project",
            changed_files=changed,
        )

    assert "telec sessions send" in instruction_a
    assert SlashCommand.NEXT_PREPARE_DRAFT.value not in instruction_a
    assert mock_guidance.await_count == 0

    # No live pair: fall back to fresh-worker guidance, no relay
    with (
        patch(
            "teleclaude.core.next_machine.prepare_scripts._find_live_session_for_slug",
            return_value=None,
        ),
        patch(
            "teleclaude.core.next_machine.prepare_scripts.compose_agent_guidance",
            return_value="guidance",
        ) as mock_guidance_b,
    ):
        _, instruction_b = await _handle_stale_grounding(
            db=AsyncMock(),
            todos_db=_mock_todos_db(),
            slug="slug-rg",
            cwd="/tmp/project",
            changed_files=changed,
        )

    mock_guidance_b.assert_awaited_once()
    assert "telec sessions send" not in instruction_b

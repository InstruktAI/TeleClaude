"""Characterization tests for the prepare state machine entrypoint."""

from __future__ import annotations

from unittest.mock import DEFAULT, AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.core.next_machine.prepare import next_prepare


def _identity(x: str) -> str:
    return x


@pytest.mark.asyncio
async def test_next_prepare_canonicalizes_cwd_from_worktree_path() -> None:
    """Regression: next_prepare must resolve worktree paths to the project root.

    When an orchestrator accidentally cd's into a worktree and calls
    ``telec todo prepare``, the raw worktree path was passed through
    uncanonicalized, causing all file lookups to hit the wrong directory.
    """
    db = AsyncMock()

    with (
        patch(
            "teleclaude.core.next_machine.prepare.resolve_canonical_project_root",
            return_value="/repo",
        ) as mock_resolve,
        patch.multiple(
            "teleclaude.core.next_machine.prepare",
            resolve_holder_children=DEFAULT,
            slug_in_roadmap=DEFAULT,
            read_phase_state=DEFAULT,
            _prepare_dispatch=DEFAULT,
        ) as prepare_mocks,
        patch("teleclaude.core.next_machine.prepare.check_artifact_staleness", return_value=[]),
    ):
        prepare_mocks["resolve_holder_children"].return_value = []
        prepare_mocks["slug_in_roadmap"].return_value = True
        prepare_mocks["read_phase_state"].return_value = {"current": PreparePhase.GATE.value}
        prepare_mocks["_prepare_dispatch"].return_value = (False, "dispatch")

        await next_prepare(db, "my-slug", "/repo/trees/my-slug")

    # resolve_canonical_project_root must be called with the original cwd
    mock_resolve.assert_called_once_with("/repo/trees/my-slug")

    # Downstream calls must receive the canonicalized "/repo", not the worktree path
    prepare_mocks["read_phase_state"].assert_called_once()
    actual_cwd = prepare_mocks["read_phase_state"].call_args[0][0]
    assert actual_cwd == "/repo", f"read_phase_state received worktree path: {actual_cwd}"

    prepare_mocks["_prepare_dispatch"].assert_called_once()
    dispatch_cwd = prepare_mocks["_prepare_dispatch"].call_args[1]["cwd"]
    assert dispatch_cwd == "/repo", f"_prepare_dispatch received worktree path: {dispatch_cwd}"


@pytest.mark.asyncio
async def test_next_prepare_dispatches_no_active_work_to_prepare_draft() -> None:
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", side_effect=_identity),
        patch("teleclaude.core.next_machine.prepare._find_next_prepare_slug", return_value=None),
        patch("teleclaude.core.next_machine.prepare.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_prepare(db, None, "/repo")

    assert 'telec sessions run --command "/next-prepare-draft" --args ""' in result


@pytest.mark.asyncio
async def test_next_prepare_returns_container_message_when_holder_has_children() -> None:
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", side_effect=_identity),
        patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=["child-a", "child-b"]),
        patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True),
    ):
        result = await next_prepare(db, "holder", "/repo")

    assert result.startswith("SPLIT FINALIZE:")
    assert "holder" in result
    assert "child-a" in result
    assert "child-b" in result


@pytest.mark.asyncio
async def test_next_prepare_uses_derived_phase_and_returns_dispatch_instruction() -> None:
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", side_effect=_identity),
        patch.multiple(
            "teleclaude.core.next_machine.prepare",
            resolve_holder_children=DEFAULT,
            slug_in_roadmap=DEFAULT,
            read_phase_state=DEFAULT,
            _prepare_dispatch=DEFAULT,
        ) as prepare_mocks,
        patch("teleclaude.core.next_machine.prepare.check_artifact_staleness", return_value=[]),
    ):
        prepare_mocks["resolve_holder_children"].return_value = []
        prepare_mocks["slug_in_roadmap"].return_value = True
        prepare_mocks["read_phase_state"].return_value = {"current": PreparePhase.GATE.value}
        prepare_mocks["_prepare_dispatch"].return_value = (False, "dispatch")
        result = await next_prepare(db, "slug-a", "/repo")

    assert result == "dispatch"

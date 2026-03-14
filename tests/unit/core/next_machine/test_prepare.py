"""Characterization tests for the prepare state machine entrypoint."""

from __future__ import annotations

from unittest.mock import DEFAULT, AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.core.next_machine.prepare import next_prepare


@pytest.mark.asyncio
async def test_next_prepare_dispatches_no_active_work_to_prepare_draft() -> None:
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.prepare._find_next_prepare_slug", return_value=None),
        patch("teleclaude.core.next_machine.prepare.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_prepare(db, None, "/repo")

    assert 'telec sessions run --command "/next-prepare-draft" --args ""' in result


@pytest.mark.asyncio
async def test_next_prepare_returns_container_message_when_holder_has_children() -> None:
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.prepare.resolve_holder_children", return_value=["child-a", "child-b"]),
        patch("teleclaude.core.next_machine.prepare.slug_in_roadmap", return_value=True),
    ):
        result = await next_prepare(db, "holder", "/repo")

    assert result.startswith("CONTAINER:")
    assert "holder" in result
    assert "child-a" in result
    assert "child-b" in result


@pytest.mark.asyncio
async def test_next_prepare_uses_derived_phase_and_returns_dispatch_instruction() -> None:
    db = AsyncMock()

    with (
        patch.multiple(
            "teleclaude.core.next_machine.prepare",
            resolve_holder_children=DEFAULT,
            slug_in_roadmap=DEFAULT,
            read_phase_state=DEFAULT,
            _derive_prepare_phase=DEFAULT,
            _prepare_dispatch=DEFAULT,
        ) as prepare_mocks,
        patch("teleclaude.core.next_machine.prepare_helpers.check_artifact_staleness", return_value=[]),
    ):
        prepare_mocks["resolve_holder_children"].return_value = []
        prepare_mocks["slug_in_roadmap"].return_value = True
        prepare_mocks["read_phase_state"].return_value = {}
        prepare_mocks["_derive_prepare_phase"].return_value = PreparePhase.GATE
        prepare_mocks["_prepare_dispatch"].return_value = (False, "dispatch")
        result = await next_prepare(db, "slug-a", "/repo")

    assert result == "dispatch"

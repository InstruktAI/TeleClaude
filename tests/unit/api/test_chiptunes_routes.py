"""Characterization tests for chiptunes routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from teleclaude.api import chiptunes_routes
from teleclaude.chiptunes.types import ChiptunesState


def _manager_stub(*, enabled: bool, last_state: ChiptunesState | None = None) -> SimpleNamespace:
    enqueued: list[tuple[str, str]] = []
    return SimpleNamespace(
        enabled=enabled,
        last_state=last_state
        or {
            "playback": "paused",
            "track_path": "/music/space_oddity.sid",
            "position_seconds": 12.5,
        },
        enqueue_command=lambda cid, action: enqueued.append((cid, action)),
        _enqueued=enqueued,
    )


class TestChiptunesRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chiptunes_status_reads_from_manager_last_state(self) -> None:
        """Status DTO is built from manager.last_state."""
        manager = _manager_stub(
            enabled=True,
            last_state={
                "playback": "playing",
                "track_path": "/music/Live_Track.sid",
                "position_seconds": 33.0,
            },
        )
        chiptunes_routes.configure(manager)
        # Reset module state
        chiptunes_routes._state_version = 7
        chiptunes_routes._pending_command_id = ""
        chiptunes_routes._pending_action = ""

        response = await chiptunes_routes.chiptunes_status()

        assert response.model_dump() == {
            "playback": "playing",
            "state_version": 7,
            "loaded": True,
            "playing": True,
            "paused": False,
            "position_seconds": 33.0,
            "track": "Live Track",
            "sid_path": "/music/Live_Track.sid",
            "pending_command_id": "",
            "pending_action": "",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chiptunes_next_returns_accepted_receipt(self) -> None:
        """Next-track requests return the issued command receipt immediately."""
        manager = _manager_stub(enabled=False)
        chiptunes_routes.configure(manager)
        chiptunes_routes._state_version = 0
        chiptunes_routes._pending_command_id = ""
        chiptunes_routes._pending_action = ""

        response = await chiptunes_routes.chiptunes_next()

        assert response.action == "next"
        assert response.status == "accepted"
        assert response.command_id  # non-empty uuid
        assert len(manager._enqueued) == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chiptunes_status_requires_manager(self) -> None:
        """Status requests return 503 when manager has not been configured."""
        chiptunes_routes.configure(None)

        with pytest.raises(HTTPException) as exc_info:
            await chiptunes_routes.chiptunes_status()

        assert exc_info.value.status_code == 503

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_clear_pending_clears_matching_command(self) -> None:
        """clear_pending resets pending state when command_id matches."""
        chiptunes_routes._pending_command_id = "abc-123"
        chiptunes_routes._pending_action = "next"

        chiptunes_routes.clear_pending("abc-123")

        assert chiptunes_routes._pending_command_id == ""
        assert chiptunes_routes._pending_action == ""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_clear_pending_ignores_non_matching_command(self) -> None:
        """clear_pending is a no-op when command_id does not match."""
        chiptunes_routes._pending_command_id = "abc-123"
        chiptunes_routes._pending_action = "next"

        chiptunes_routes.clear_pending("different-id")

        assert chiptunes_routes._pending_command_id == "abc-123"
        assert chiptunes_routes._pending_action == "next"

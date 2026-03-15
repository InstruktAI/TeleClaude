"""Characterization tests for chiptunes routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from teleclaude.api import chiptunes_routes


def _runtime_settings_stub(*, manager_enabled: bool) -> SimpleNamespace:
    runtime_state = SimpleNamespace(
        playback="paused",
        track_path="/music/space_oddity.sid",
        position_seconds=12.5,
        pending_command_id="cmd-1",
        pending_action="pause",
    )
    manager = SimpleNamespace(
        enabled=manager_enabled,
        current_track="Live Track" if manager_enabled else "",
        current_sid_path="/music/live.sid" if manager_enabled else "",
        is_playing=manager_enabled,
        is_paused=not manager_enabled,
        capture_runtime_state=lambda: SimpleNamespace(
            playback="playing",
            position_seconds=33.0,
            pending_command_id="cmd-2",
            pending_action="next",
        ),
    )
    return SimpleNamespace(
        _chiptunes_manager=manager,
        chiptunes_state_version=7,
        get_state=lambda: SimpleNamespace(chiptunes=runtime_state),
        issue_chiptunes_command=lambda action: f"{action}-123",
    )


class TestChiptunesRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chiptunes_status_prefers_live_manager_state_when_enabled(self) -> None:
        """Live-manager state overrides the stored runtime snapshot when the manager is enabled."""
        chiptunes_routes.configure(_runtime_settings_stub(manager_enabled=True))

        response = await chiptunes_routes.chiptunes_status()

        assert response.model_dump() == {
            "playback": "playing",
            "state_version": 7,
            "loaded": True,
            "playing": True,
            "paused": False,
            "position_seconds": 33.0,
            "track": "Live Track",
            "sid_path": "/music/live.sid",
            "pending_command_id": "cmd-2",
            "pending_action": "next",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chiptunes_next_returns_accepted_receipt(self) -> None:
        """Next-track requests return the issued command receipt immediately."""
        chiptunes_routes.configure(_runtime_settings_stub(manager_enabled=False))

        response = await chiptunes_routes.chiptunes_next()

        assert response.model_dump() == {
            "status": "accepted",
            "command_id": "next-123",
            "action": "next",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chiptunes_status_requires_runtime_settings(self) -> None:
        """Status requests return 503 when runtime settings have not been configured."""
        chiptunes_routes.configure(None)

        with pytest.raises(HTTPException) as exc_info:
            await chiptunes_routes.chiptunes_status()

        assert exc_info.value.status_code == 503

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.cli.tui import app_media


class _MediaApp(app_media.TelecAppMediaMixin):
    def __init__(self, footer: object) -> None:
        self._footer = footer
        self._chiptunes_state_version = 3
        self.api = SimpleNamespace(
            chiptunes_pause=AsyncMock(return_value=SimpleNamespace(command_id="cmd-pause", action="pause")),
            chiptunes_resume=AsyncMock(return_value=SimpleNamespace(command_id="cmd-resume", action="resume")),
        )
        self.notify = Mock()
        self._schedule_chiptunes_reconcile = Mock()

    def query_one(self, *_args: object, **_kwargs: object) -> object:
        return self._footer

    async def _sync_chiptunes_footer_state(self) -> None:
        return None


@pytest.mark.unit
def test_apply_chiptunes_footer_state_ignores_stale_versions_and_updates_newer_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    favorites = __import__("teleclaude.chiptunes.favorites", fromlist=["is_favorited"])
    monkeypatch.setattr(favorites, "is_favorited", lambda path: path.endswith(".sid"))
    footer = SimpleNamespace(
        chiptunes_loaded=False,
        chiptunes_playback="cold",
        chiptunes_playing=False,
        chiptunes_track="",
        chiptunes_sid_path="",
        chiptunes_pending_command_id="",
        chiptunes_pending_action="",
        chiptunes_favorited=False,
    )
    app = _MediaApp(footer)

    app._apply_chiptunes_footer_state(
        loaded=True,
        playback="playing",
        state_version=2,
        playing=True,
        track="old",
        sid_path="old.sid",
        pending_command_id="old",
        pending_action="resume",
    )
    assert footer.chiptunes_track == ""

    app._apply_chiptunes_footer_state(
        loaded=True,
        playback="playing",
        state_version=4,
        playing=True,
        track="new",
        sid_path="new.sid",
        pending_command_id="cmd",
        pending_action="resume",
    )

    assert app._chiptunes_state_version == 4
    assert footer.chiptunes_track == "new"
    assert footer.chiptunes_favorited is True


@pytest.mark.unit
def test_apply_chiptunes_receipt_marks_resume_and_skip_actions_as_loading() -> None:
    footer = SimpleNamespace(
        chiptunes_pending_command_id="",
        chiptunes_pending_action="",
        chiptunes_playback="paused",
    )
    app = _MediaApp(footer)

    app._apply_chiptunes_receipt("cmd-1", "resume")

    assert footer.chiptunes_pending_command_id == "cmd-1"
    assert footer.chiptunes_pending_action == "resume"
    assert footer.chiptunes_playback == "loading"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("playing", "expected_method", "expected_action"),
    [(True, "chiptunes_pause", "pause"), (False, "chiptunes_resume", "resume")],
)
async def test_chiptunes_play_pause_toggles_local_playing_state_and_reconciles(
    playing: bool,
    expected_method: str,
    expected_action: str,
) -> None:
    footer = SimpleNamespace(
        chiptunes_playing=playing,
        chiptunes_pending_command_id="",
        chiptunes_pending_action="",
        chiptunes_playback="cold",
    )
    app = _MediaApp(footer)

    await app_media.TelecAppMediaMixin._chiptunes_play_pause.__wrapped__(app)

    getattr(app.api, expected_method).assert_awaited_once()
    assert footer.chiptunes_playing is (not playing)
    assert footer.chiptunes_pending_action == expected_action
    app._schedule_chiptunes_reconcile.assert_called_once_with()

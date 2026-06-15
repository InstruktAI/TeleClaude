"""Functional tests for ChipTunes footer gate visibility."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult

from teleclaude.cli.tui import app_media
from teleclaude.cli.tui.app_media import TelecAppMediaMixin
from teleclaude.cli.tui.widgets.telec_footer import FooterActionButton, TelecFooter
from teleclaude.config import ChiptunesConfig

pytestmark = pytest.mark.functional

FOOTER_SELECTOR = "#telec-footer"
PREV_SELECTOR = "#footer-prev"
PLAY_SELECTOR = "#footer-play"
STOP_SELECTOR = "#footer-stop"
NEXT_SELECTOR = "#footer-next"
FAV_SELECTOR = "#footer-fav"
DISLIKE_SELECTOR = "#footer-dislike"
COLD_PLAYBACK = "cold"


class FooterTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield TelecFooter(id=FOOTER_SELECTOR.removeprefix("#"))


class MediaFooterTestApp(TelecAppMediaMixin, App[None]):
    _chiptunes_state_version = -1

    def compose(self) -> ComposeResult:
        yield TelecFooter(id=FOOTER_SELECTOR.removeprefix("#"))


def _transport_buttons(footer: TelecFooter) -> list[FooterActionButton]:
    return [
        footer.query_one(PREV_SELECTOR, FooterActionButton),
        footer.query_one(PLAY_SELECTOR, FooterActionButton),
        footer.query_one(STOP_SELECTOR, FooterActionButton),
        footer.query_one(NEXT_SELECTOR, FooterActionButton),
        footer.query_one(FAV_SELECTOR, FooterActionButton),
        footer.query_one(DISLIKE_SELECTOR, FooterActionButton),
    ]


@pytest.mark.asyncio
async def test_footer_hides_and_disables_chiptunes_transport_until_gate_enabled() -> None:
    app = FooterTestApp()
    async with app.run_test() as pilot:
        footer = app.screen.query_one(FOOTER_SELECTOR, TelecFooter)
        await pilot.pause()

        assert [button.display for button in _transport_buttons(footer)] == [False] * 6
        assert [button.disabled for button in _transport_buttons(footer)] == [True] * 6

        footer.chiptunes_enabled = True
        await pilot.pause()

        assert [button.display for button in _transport_buttons(footer)] == [True] * 6
        assert footer.query_one(PLAY_SELECTOR, FooterActionButton).disabled is False
        assert footer.query_one(PREV_SELECTOR, FooterActionButton).disabled is True


@pytest.mark.asyncio
async def test_app_media_applies_chiptunes_config_gate_to_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = MediaFooterTestApp()
    monkeypatch.setattr(
        app_media.config_mod,
        "config",
        SimpleNamespace(chiptunes=ChiptunesConfig(enabled=True)),
    )

    async with app.run_test() as pilot:
        app._apply_chiptunes_footer_state(
            loaded=False,
            playback=COLD_PLAYBACK,
            state_version=0,
            playing=False,
            track="",
            sid_path="",
            pending_command_id="",
            pending_action="",
        )
        await pilot.pause()

        footer = app.screen.query_one(FOOTER_SELECTOR, TelecFooter)
        assert footer.chiptunes_enabled is True

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.cli.tui import app_media
from teleclaude.cli.tui.animation_observability import AnimationPerfTracker
from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar


class _MediaApp(app_media.TelecAppMediaMixin):
    def __init__(self, footer: object) -> None:
        self._footer = footer
        self._chiptunes_state_version = 3
        self._animation_perf = AnimationPerfTracker(slow_frame_threshold_ms=1.0, warning_interval_ticks=9999)
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
    # Patch the already-bound reference in app_media, not the origin module.
    monkeypatch.setattr(app_media, "is_favorited", lambda path: path.endswith(".sid"))
    monkeypatch.setattr(app_media, "is_disliked", lambda path: False)
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
    ("playing", "expected_method", "expected_pending_action", "reconcile_expected"),
    [
        # Pause path tracks the receipt and schedules reconcile.
        (True, "chiptunes_pause", "pause", True),
        # Resume path skips receipt tracking and reconcile — WS events correct the state
        # once the worker is up, so the button flips to "pause" immediately.
        (False, "chiptunes_resume", "", False),
    ],
)
async def test_chiptunes_play_pause_toggles_local_playing_state_and_reconciles(
    playing: bool,
    expected_method: str,
    expected_pending_action: str,
    reconcile_expected: bool,
) -> None:
    footer = SimpleNamespace(
        chiptunes_playing=playing,
        chiptunes_loaded=False,
        chiptunes_pending_command_id="",
        chiptunes_pending_action="",
        chiptunes_playback="cold",
    )
    app = _MediaApp(footer)

    await app_media.TelecAppMediaMixin._chiptunes_play_pause.__wrapped__(app)

    getattr(app.api, expected_method).assert_awaited_once()
    assert footer.chiptunes_playing is (not playing)
    assert footer.chiptunes_pending_action == expected_pending_action
    if reconcile_expected:
        app._schedule_chiptunes_reconcile.assert_called_once_with()
    else:
        app._schedule_chiptunes_reconcile.assert_not_called()


@pytest.mark.unit
def test_animation_tick_precomputes_and_caches_header_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    footer = SimpleNamespace()
    app = _MediaApp(footer)
    banner = Banner()
    tab_bar = BoxTabBar()
    banner.refresh = Mock()
    tab_bar.refresh = Mock()
    app._animation_engine = SimpleNamespace(update=Mock(return_value=True))

    sentinel_banner = object()
    sentinel_tabs = object()
    monkeypatch.setattr(
        "teleclaude.cli.tui.header_frames.build_header_frames",
        lambda *, banner, tab_bar: (sentinel_banner, sentinel_tabs),
    )
    app.query_one = Mock(side_effect=[banner, tab_bar])

    app._animation_tick()

    assert banner._cached_render is sentinel_banner
    assert tab_bar._cached_render is sentinel_tabs
    banner.refresh.assert_called_once()
    tab_bar.refresh.assert_called_once()


@pytest.mark.unit
def test_record_animation_tick_emits_health_log_after_consecutive_slow_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    footer = SimpleNamespace()
    app = _MediaApp(footer)
    app._animation_perf = AnimationPerfTracker(slow_frame_threshold_ms=1.0, warning_interval_ticks=9999)
    app._header_entity_count = Mock(return_value=7)
    info = Mock()
    monkeypatch.setattr(app_media.logger, "info", info)

    app._record_animation_tick(changed=True, total_ms=2.0, update_ms=1.0, build_ms=1.0)
    app._record_animation_tick(changed=True, total_ms=2.0, update_ms=1.0, build_ms=1.0)
    app._record_animation_tick(changed=True, total_ms=2.0, update_ms=1.0, build_ms=1.0)

    assert info.call_count == 1


@pytest.mark.unit
def test_log_animation_health_reports_current_entity_count(monkeypatch: pytest.MonkeyPatch) -> None:
    footer = SimpleNamespace()
    app = _MediaApp(footer)
    app._animation_perf.record_tick(changed=True, total_ms=3.0, update_ms=1.0, build_ms=2.0)
    app._header_entity_count = Mock(return_value=11)
    info = Mock()
    monkeypatch.setattr(app_media.logger, "info", info)

    app._log_animation_health(reason="tick")

    assert info.call_args.kwargs["header_entity_count"] == 11


@pytest.mark.unit
def test_record_animation_tick_emits_periodic_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    footer = SimpleNamespace()
    app = _MediaApp(footer)
    app._animation_perf = AnimationPerfTracker(
        slow_frame_threshold_ms=1000.0,
        warning_interval_ticks=9999,
        baseline_interval_ticks=2,
    )
    app._header_entity_count = Mock(return_value=5)
    info = Mock()
    monkeypatch.setattr(app_media.logger, "info", info)

    app._record_animation_tick(changed=True, total_ms=2.0, update_ms=1.0, build_ms=1.0)
    app._record_animation_tick(changed=True, total_ms=2.0, update_ms=1.0, build_ms=1.0)

    assert info.call_args.kwargs["reason"] == "baseline"

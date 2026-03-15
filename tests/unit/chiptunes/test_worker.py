"""Characterization tests for teleclaude.chiptunes.worker."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import teleclaude.chiptunes.worker as worker_module
from teleclaude.config.runtime_settings import ChiptunesRuntimeState


class _ImmediateThread:
    def __init__(
        self,
        target: Callable[..., object],
        args: tuple[object, ...] = (),
        kwargs: Mapping[str, object] | None = None,
        daemon: bool | None = None,
        name: str | None = None,
    ) -> None:
        self.target = target
        self.args = args
        self.kwargs: Mapping[str, object] = dict(kwargs or {})
        self.daemon = daemon
        self.name = name

    def start(self) -> None:
        if self.name == "chiptunes-commands":
            return
        self.target(*self.args, **self.kwargs)


class _FakePlayer:
    instances: list[_FakePlayer] = []

    def __init__(self, volume: float) -> None:
        self.volume = volume
        self.play_calls: list[tuple[Path, bool, float]] = []
        self.stop_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.is_playing = False
        self.is_paused = False
        self.playback_position_seconds = 0.0
        self.track_end_reason: str | None = None
        self.on_track_end = None
        type(self).instances.append(self)

    def play(self, track: Path, *, start_paused: bool = False, start_position_seconds: float = 0.0) -> None:
        self.play_calls.append((track, start_paused, start_position_seconds))
        self.is_paused = start_paused
        self.is_playing = not start_paused
        self.playback_position_seconds = start_position_seconds

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_playing = False
        self.is_paused = False

    def pause(self) -> None:
        self.pause_calls += 1
        self.is_paused = True
        self.is_playing = False

    def resume(self) -> None:
        self.resume_calls += 1
        self.is_paused = False
        self.is_playing = True


def _patch_worker_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakePlayer.instances.clear()
    monkeypatch.setattr(worker_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(worker_module, "ChiptunesPlayer", _FakePlayer)


@pytest.mark.unit
class TestWorker:
    def test_enable_starts_first_track_and_records_history(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_worker_runtime(monkeypatch)
        track = tmp_path / "Lazy_Jones.sid"
        changes: list[str] = []
        worker = worker_module._Worker(lambda: track, volume=0.4, on_state_change=lambda: changes.append("state"))

        worker.enable(start_paused=True)

        player = _FakePlayer.instances[-1]
        assert worker.current_track == track
        assert worker.current_track_label == "Lazy Jones"
        assert player.play_calls == [(track, True, 0.0)]
        assert worker.capture_runtime_state() == ChiptunesRuntimeState(
            playback="paused",
            track_path=str(track),
            position_seconds=0.0,
            history=[str(track)],
            history_index=0,
            pending_command_id="",
            pending_action="",
        )
        assert changes

    def test_start_from_state_reloads_current_track_with_saved_position(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_worker_runtime(monkeypatch)
        track = tmp_path / "Commando.sid"
        state = ChiptunesRuntimeState(
            playback="paused",
            track_path=str(track),
            position_seconds=7.25,
            history=[str(track)],
            history_index=0,
        )
        worker = worker_module._Worker(lambda: track, volume=0.4)

        worker.start_from_state(state)

        player = _FakePlayer.instances[-1]
        assert player.play_calls == [(track, True, 7.25)]
        assert worker.current_track == track
        assert worker.is_paused is True

    def test_disable_stops_player_and_clears_runtime_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_worker_runtime(monkeypatch)
        track = tmp_path / "Delta.sid"
        worker = worker_module._Worker(lambda: track, volume=0.4)
        worker.enable()
        player = _FakePlayer.instances[-1]

        worker.disable()

        assert player.stop_calls == 1
        assert worker.current_track is None
        assert worker.capture_runtime_state().playback == "cold"

    def test_pause_and_resume_delegate_to_loaded_player(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _patch_worker_runtime(monkeypatch)
        track = tmp_path / "Last_Ninja.sid"
        worker = worker_module._Worker(lambda: track, volume=0.4)
        worker.enable()
        player = _FakePlayer.instances[-1]
        player.playback_position_seconds = 12.5

        worker.pause()
        worker.resume()

        assert player.pause_calls == 1
        assert player.resume_calls == 1
        assert worker.capture_runtime_state().playback == "playing"

    def test_history_navigation_moves_between_previous_and_new_tracks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_worker_runtime(monkeypatch)
        tracks = [tmp_path / "A.sid", tmp_path / "B.sid"]
        worker = worker_module._Worker(lambda: tracks.pop(0), volume=0.4)
        worker.enable()

        worker.handle_cmd({"cmd": "next"})
        worker.handle_cmd({"cmd": "prev"})

        assert worker.current_track == tmp_path / "A.sid"
        assert worker.capture_runtime_state().history == [str(tmp_path / "A.sid"), str(tmp_path / "B.sid")]
        assert worker.capture_runtime_state().history_index == 0

    def test_track_end_auto_advances_only_for_normal_completion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_worker_runtime(monkeypatch)
        tracks = [tmp_path / "First.sid", tmp_path / "Second.sid"]
        worker = worker_module._Worker(lambda: tracks.pop(0), volume=0.4)
        worker.enable()
        current_gen = worker._playback_gen

        worker._on_track_end("track_completed", gen=current_gen)
        assert worker.current_track == tmp_path / "Second.sid"

        worker._on_track_end("init_failed", gen=worker._playback_gen)
        assert worker.current_track == tmp_path / "Second.sid"

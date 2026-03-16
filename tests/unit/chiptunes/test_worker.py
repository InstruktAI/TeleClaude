"""Tests for teleclaude.chiptunes.worker — subprocess playback worker."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import teleclaude.chiptunes.worker as worker_module
from teleclaude.chiptunes.worker import _WorkerProcess


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

    def __init__(self, volume: float, max_track_duration: float = 300.0) -> None:
        self.volume = volume
        self.max_track_duration = max_track_duration
        self.play_calls: list[tuple[Path, bool, float]] = []
        self.stop_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.is_playing = False
        self.is_paused = False
        self.playback_position_seconds = 0.0
        self.track_end_reason: str | None = None
        self.on_track_end: Callable[[str | None], None] | None = None
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


def _make_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tracks: list[Path] | None = None,
) -> _WorkerProcess:
    _patch_worker_runtime(monkeypatch)
    music_dir = tmp_path / "music"
    worker = _WorkerProcess(music_dir, volume=0.4)
    if tracks is not None:
        remaining = list(tracks)
        worker._track_list = remaining
        worker._pick_random_track = lambda: remaining.pop(0) if remaining else None
    return worker


@pytest.mark.unit
class TestWorkerProcess:
    def test_start_plays_first_track_and_emits_event(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        track = tmp_path / "Lazy_Jones.sid"
        worker = _make_worker(monkeypatch, tmp_path, tracks=[track])
        emitted: list[Mapping[str, object]] = []
        worker._emit = lambda event, **kw: emitted.append({"event": event, **kw})
        worker._enabled = True
        worker._play_next()

        player = _FakePlayer.instances[-1]
        assert player.play_calls == [(track, False, 0.0)]
        assert worker._current_track == track
        assert any(e.get("event") == "track_start" for e in emitted)

    def test_start_paused_creates_paused_player(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        track = tmp_path / "Commando.sid"
        worker = _make_worker(monkeypatch, tmp_path, tracks=[track])
        worker._emit = lambda event, **kw: None
        worker._enabled = True
        worker._paused_requested = True
        worker._play_next()

        player = _FakePlayer.instances[-1]
        assert player.play_calls == [(track, True, 0.0)]

    def test_restore_state_resumes_track_at_position(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        track = tmp_path / "Delta.sid"
        worker = _make_worker(monkeypatch, tmp_path, tracks=[track])
        worker._emit = lambda event, **kw: None
        worker._restore_state(
            {
                "playback": "paused",
                "track_path": str(track),
                "position_seconds": 7.25,
                "history": [str(track)],
                "history_index": 0,
            }
        )

        player = _FakePlayer.instances[-1]
        assert player.play_calls == [(track, True, 7.25)]
        assert worker._current_track == track

    def test_disable_stops_player_and_clears_state(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        track = tmp_path / "Last_Ninja.sid"
        worker = _make_worker(monkeypatch, tmp_path, tracks=[track])
        worker._emit = lambda event, **kw: None
        worker._enabled = True
        worker._play_next()
        player = _FakePlayer.instances[-1]

        worker._disable()

        assert player.stop_calls == 1
        assert worker._current_track is None
        assert worker._enabled is False

    def test_pause_and_resume_delegate_to_player(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        track = tmp_path / "Parallax.sid"
        worker = _make_worker(monkeypatch, tmp_path, tracks=[track])
        worker._emit = lambda event, **kw: None
        worker._enabled = True
        worker._play_next()
        player = _FakePlayer.instances[-1]
        player.playback_position_seconds = 12.5

        worker._do_pause()
        assert player.pause_calls == 1
        assert worker._paused_requested is True

        worker._do_resume()
        assert player.resume_calls == 1

    def test_history_navigation_prev_next(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        tracks = [tmp_path / "A.sid", tmp_path / "B.sid"]
        worker = _make_worker(monkeypatch, tmp_path, tracks=tracks)
        worker._emit = lambda event, **kw: None
        worker._enabled = True
        worker._play_next()  # plays A
        worker._play_next()  # plays B
        worker._play_prev()  # back to A

        assert worker._current_track == tmp_path / "A.sid"
        assert worker._history_index == 0

    def test_track_end_auto_advances_only_for_normal_completion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        tracks = [tmp_path / "First.sid", tmp_path / "Second.sid"]
        worker = _make_worker(monkeypatch, tmp_path, tracks=tracks)
        worker._emit = lambda event, **kw: None
        worker._enabled = True
        worker._play_next()
        current_gen = worker._playback_gen

        worker._on_track_end("track_completed", gen=current_gen)
        assert worker._current_track == tmp_path / "Second.sid"

        worker._on_track_end("init_failed", gen=worker._playback_gen)
        assert worker._current_track == tmp_path / "Second.sid"

    def test_stale_generation_callback_ignored(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        tracks = [tmp_path / "One.sid", tmp_path / "Two.sid"]
        worker = _make_worker(monkeypatch, tmp_path, tracks=tracks)
        worker._emit = lambda event, **kw: None
        worker._enabled = True
        worker._play_next()
        stale_gen = worker._playback_gen

        worker._play_next()  # advances gen
        worker._on_track_end("track_completed", gen=stale_gen)

        # Should not have advanced beyond Two.sid
        assert worker._current_track == tmp_path / "Two.sid"

    def test_process_command_dispatches_json(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        track = tmp_path / "Sanxion.sid"
        worker = _make_worker(monkeypatch, tmp_path, tracks=[track])
        worker._emit = lambda event, **kw: None
        worker._process_command(json.dumps({"cmd": "start"}))
        assert worker._current_track == track

        worker._process_command(json.dumps({"cmd": "pause"}))
        player = _FakePlayer.instances[-1]
        assert player.pause_calls == 1

        worker._process_command(json.dumps({"cmd": "capture_state"}))
        # Should not crash — emits state update

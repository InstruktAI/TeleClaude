"""Characterization tests for teleclaude.chiptunes.manager."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import teleclaude.chiptunes.manager as manager_module
from teleclaude.config.runtime_settings import ChiptunesRuntimeState


class _FakeWorker:
    instances: list[_FakeWorker] = []

    def __init__(
        self,
        pick_random_track: Callable[[], Path | None],
        volume: float,
        on_track_start: Callable[[str, str], None] | None,
        on_state_change: Callable[[], None] | None,
    ) -> None:
        self.pick_random_track = pick_random_track
        self.volume = volume
        self.on_track_start = on_track_start
        self.on_state_change = on_state_change
        self.enable_calls: list[bool] = []
        self.started_states: list[ChiptunesRuntimeState] = []
        self.disable_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.command_payloads: list[Mapping[str, str]] = []
        self.command_queue: list[tuple[str, str]] = []
        self.is_playing = False
        self.is_paused = False
        self.current_track_label = ""
        self.current_track: Path | None = None
        self.runtime_state = ChiptunesRuntimeState()
        _FakeWorker.instances.append(self)

    def enable(self, *, start_paused: bool = False) -> None:
        self.enable_calls.append(start_paused)

    def start_from_state(self, state: ChiptunesRuntimeState) -> None:
        self.started_states.append(state)

    def disable(self) -> None:
        self.disable_calls += 1

    def pause(self) -> None:
        self.pause_calls += 1

    def resume(self) -> None:
        self.resume_calls += 1

    def handle_cmd(self, payload: Mapping[str, str]) -> None:
        self.command_payloads.append(payload)

    def enqueue_command(self, command_id: str, action: str) -> None:
        self.command_queue.append((command_id, action))

    def capture_runtime_state(self) -> ChiptunesRuntimeState:
        return self.runtime_state


def _make_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> manager_module.ChiptunesManager:
    _FakeWorker.instances.clear()
    monkeypatch.setattr(manager_module, "_Worker", _FakeWorker)
    return manager_module.ChiptunesManager(tmp_path / "music", volume=0.25)


@pytest.mark.unit
class TestChiptunesManager:
    def test_start_stop_and_navigation_delegate_to_worker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        manager = _make_manager(monkeypatch, tmp_path)
        worker = _FakeWorker.instances[-1]

        manager.start(paused=True)
        manager.pause()
        manager.resume()
        manager.next_track()
        manager.prev_track()
        manager.enqueue_command("cmd-1", "next")
        manager.stop()

        assert manager.enabled is False
        assert worker.enable_calls == [True]
        assert worker.pause_calls == 1
        assert worker.resume_calls == 1
        assert worker.command_payloads == [{"cmd": "next"}, {"cmd": "prev"}]
        assert worker.command_queue == [("cmd-1", "next")]
        assert worker.disable_calls == 1

    def test_track_properties_and_callbacks_are_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        manager = _make_manager(monkeypatch, tmp_path)
        worker = _FakeWorker.instances[-1]
        worker.current_track = tmp_path / "Great_Giana_Sisters.sid"
        worker.current_track_label = "Great Giana Sisters"

        started: list[tuple[str, str]] = []
        state_changes: list[str] = []
        manager.on_track_start = lambda track_label, sid_path: started.append((track_label, sid_path))
        manager.on_state_change = lambda: state_changes.append("changed")

        manager._on_track_start("Great Giana Sisters", str(worker.current_track))
        manager._on_state_change()

        assert manager.current_track == "Great Giana Sisters"
        assert manager.current_sid_path == str(worker.current_track)
        assert started == [("Great Giana Sisters", str(worker.current_track))]
        assert state_changes == ["changed"]

    def test_capture_runtime_state_updates_enabled_based_on_playback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        manager = _make_manager(monkeypatch, tmp_path)
        worker = _FakeWorker.instances[-1]

        worker.runtime_state = ChiptunesRuntimeState(playback="playing")
        assert manager.capture_runtime_state().playback == "playing"
        assert manager.enabled is True

        worker.runtime_state = ChiptunesRuntimeState(playback="cold")
        assert manager.capture_runtime_state().playback == "cold"
        assert manager.enabled is False

    def test_pick_random_track_caches_discovery_results(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        manager = _make_manager(monkeypatch, tmp_path)
        track = tmp_path / "music" / "track.sid"
        calls: list[str] = []

        monkeypatch.setattr(manager_module.random, "choice", lambda items: items[-1])
        monkeypatch.setattr(manager, "_discover_tracks", lambda: calls.append("discover") or [track])

        assert manager._pick_random_track() == track
        assert manager._pick_random_track() == track
        assert calls == ["discover"]

    def test_discover_tracks_filters_rsid_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        music_dir = tmp_path / "music"
        music_dir.mkdir()
        psid = music_dir / "good.sid"
        rsid = music_dir / "skip.sid"
        psid.write_bytes(b"PSIDpayload")
        rsid.write_bytes(b"RSIDpayload")

        manager = _make_manager(monkeypatch, tmp_path)
        manager._music_dir = music_dir

        assert manager._discover_tracks() == [psid]

"""Characterization tests for teleclaude.chiptunes.player."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.chiptunes.player as player_module
from teleclaude.chiptunes.sid_parser import SIDHeader


class _RecordingThread:
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
        self.started = False

    def start(self) -> None:
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return False


class _FakeDriver:
    def __init__(self, header: SIDHeader) -> None:
        self.header = header
        self.init_calls: list[int] = []
        self.play_calls = 0

    def init_tune(self, subtune: int) -> None:
        self.init_calls.append(subtune)

    def play_frame(self) -> list[tuple[int, int]]:
        self.play_calls += 1
        return [(0, self.play_calls)]


class _FakeRenderer:
    def __init__(self, sample_rate: int, pal: bool, volume: float) -> None:
        self.sample_rate = sample_rate
        self.pal = pal
        self.volume = volume
        self.frames: list[tuple[list[tuple[int, int]], float]] = []

    def render_frame(self, writes: list[tuple[int, int]], frame_duration_s: float) -> bytes:
        self.frames.append((writes, frame_duration_s))
        return b"\x01\x02"


def _header(*, flags: int = 0, speed: int = 0, start_song: int = 1) -> SIDHeader:
    return SIDHeader(
        magic=b"PSID",
        version=2,
        data_offset=124,
        load_address=0x1000,
        init_address=0x1003,
        play_address=0x1006,
        songs=1,
        start_song=start_song,
        speed=speed,
        name="Song",
        author="Author",
        released="1988",
        flags=flags,
        payload=b"\xea",
    )


@pytest.mark.unit
class TestChiptunesPlayer:
    def test_play_requires_sounddevice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(player_module, "_sounddevice_available", False)
        player = player_module.ChiptunesPlayer()

        with pytest.raises(ImportError):
            player.play(Path("song.sid"))

    def test_play_parse_failure_reports_sid_parse_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(player_module, "_sounddevice_available", True)
        monkeypatch.setattr(player_module, "parse_sid_file", lambda path: (_ for _ in ()).throw(ValueError("bad sid")))
        player = player_module.ChiptunesPlayer()
        reasons: list[str | None] = []
        player.on_track_end = reasons.append

        player.play(Path("broken.sid"))

        assert player.track_end_reason == "sid_parse_failed"
        assert reasons == ["sid_parse_failed"]
        assert player.is_playing is False

    def test_play_start_paused_initializes_thread_and_position(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(player_module, "_sounddevice_available", True)
        monkeypatch.setattr(player_module, "parse_sid_file", lambda path: _header(flags=4))
        monkeypatch.setattr(player_module, "is_pal", lambda header: True)
        monkeypatch.setattr(player_module.threading, "Thread", _RecordingThread)
        player = player_module.ChiptunesPlayer(volume=0.75)

        player.play(Path("song.sid"), start_paused=True, start_position_seconds=1.5)

        assert isinstance(player._thread, _RecordingThread)
        assert player._thread.started is True
        assert player._thread.args == (_header(flags=4), 1.5)
        assert player.is_paused is True
        assert player.playback_position_seconds == 1.5
        assert player._stream_blocksize == int(48000 * (1.0 / 50.0)) * 4
        assert player._resume_event.is_set() is False

    def test_stream_callback_consumes_buffered_audio_then_zero_fills(self) -> None:
        player = player_module.ChiptunesPlayer()
        player._callback_remainder = b"ab"
        player._pcm_queue.put_nowait(b"cde")
        out = bytearray(8)

        player._stream_callback(out, 4, None, SimpleNamespace())

        assert bytes(out) == b"abcde\x00\x00\x00"
        assert player._callback_remainder == b""

    def test_resume_reopens_stream_and_sets_resume_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        player = player_module.ChiptunesPlayer()
        player._paused = True
        player._playing = True
        player._stream = None
        player._stream_blocksize = 32
        player._resume_event.clear()
        calls: list[str] = []
        monkeypatch.setattr(player, "_open_stream", lambda: calls.append("open") or True)

        player.resume()

        assert calls == ["open"]
        assert player.is_paused is False
        assert player._resume_event.is_set() is True

    def test_emulation_loop_marks_init_failure_when_driver_setup_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(player_module, "SIDDriver", lambda header: (_ for _ in ()).throw(RuntimeError("no cpu")))
        player = player_module.ChiptunesPlayer()
        reasons: list[str | None] = []
        player.on_track_end = reasons.append

        player._emulation_loop(_header())

        assert player.track_end_reason == "init_failed"
        assert reasons == ["init_failed"]

    def test_emulation_loop_updates_position_and_reports_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = _FakeDriver(_header())
        renderer = _FakeRenderer(sample_rate=48000, pal=True, volume=0.5)
        monkeypatch.setattr(player_module, "SIDDriver", lambda header: driver)
        monkeypatch.setattr(player_module, "SIDRenderer", lambda sample_rate, pal, volume: renderer)
        player = player_module.ChiptunesPlayer(volume=0.5, max_track_duration=1.0 / 50.0)
        reasons: list[str | None] = []
        player.on_track_end = reasons.append
        monkeypatch.setattr(player, "_enqueue_pcm", lambda pcm, frame_duration: True)

        player._emulation_loop(_header(flags=4))

        assert driver.init_calls == [0]
        assert renderer.frames == [([(0, 1)], 1.0 / 50.0)]
        assert player.playback_position_seconds == pytest.approx(1.0 / 50.0)
        assert player.track_end_reason == "track_completed"
        assert reasons == ["track_completed"]

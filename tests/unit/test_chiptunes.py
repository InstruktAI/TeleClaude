"""Unit tests for the chiptunes SID playback feature."""

from __future__ import annotations

import struct
import threading
import asyncio
import queue
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- Helper: build a minimal PSID v2 file in memory ---

def _build_psid(
    name: bytes = b"Test Tune\x00",
    author: bytes = b"Composer\x00",
    released: bytes = b"2024\x00",
    load_address: int = 0x1000,
    init_address: int = 0x1000,
    play_address: int = 0x1003,
    songs: int = 1,
    start_song: int = 1,
    speed: int = 0,
    flags: int = 0x0004,  # PAL flag
    payload: bytes = b"\xea\xea\x60",  # NOP NOP RTS
    version: int = 2,
    data_offset: int = 124,
) -> bytes:
    """Build a minimal PSID v2 file."""
    # Fixed-size v1 header: magic(4) version(2) data_offset(2) load(2) init(2) play(2)
    #   songs(2) start_song(2) speed(4) name(32) author(32) released(32)
    name_field = name.ljust(32, b"\x00")[:32]
    author_field = author.ljust(32, b"\x00")[:32]
    released_field = released.ljust(32, b"\x00")[:32]

    v1 = struct.pack(
        ">4sHHHHHHHI32s32s32s",
        b"PSID",
        version,
        data_offset,
        load_address,
        init_address,
        play_address,
        songs,
        start_song,
        speed,
        name_field,
        author_field,
        released_field,
    )

    # v2 extras: flags(2) + 4 reserved bytes
    v2_extra = struct.pack(">H4B", flags, 0, 0, 0, 0)

    # Pad header to data_offset, then append payload
    header = v1 + v2_extra
    padding = bytes(data_offset - len(header))
    return header + padding + payload


# --- Task 1.1: SID header parser tests ---

class TestSIDParser:
    def test_parse_valid_psid(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.sid_parser import parse_sid_file

        sid_data = _build_psid()
        sid_file = tmp_path / "test.sid"
        sid_file.write_bytes(sid_data)

        header = parse_sid_file(sid_file)
        assert header.magic == b"PSID"
        assert header.version == 2
        assert header.load_address == 0x1000
        assert header.init_address == 0x1000
        assert header.play_address == 0x1003
        assert header.songs == 1
        assert header.start_song == 1
        assert header.name == "Test Tune"
        assert header.author == "Composer"

    def test_parse_embedded_load_address(self, tmp_path: Path) -> None:
        """load_address=0 means first 2 payload bytes are the real address."""
        from teleclaude.chiptunes.sid_parser import parse_sid_file

        # Payload: LE load address (0x2000) + NOP NOP RTS
        embedded_payload = struct.pack("<H", 0x2000) + b"\xea\xea\x60"
        sid_data = _build_psid(load_address=0, payload=embedded_payload)
        sid_file = tmp_path / "embedded.sid"
        sid_file.write_bytes(sid_data)

        header = parse_sid_file(sid_file)
        assert header.load_address == 0x2000
        assert header.payload == b"\xea\xea\x60"

    def test_reject_rsid_with_zero_play_address(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.sid_parser import parse_sid_file

        # Build an RSID with play_address=0
        sid_data = _build_psid(play_address=0)
        # Replace PSID magic with RSID
        sid_data = b"RSID" + sid_data[4:]
        sid_file = tmp_path / "bad.sid"
        sid_file.write_bytes(sid_data)

        with pytest.raises(ValueError, match="interrupt-driven"):
            parse_sid_file(sid_file)

    def test_reject_invalid_magic(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.sid_parser import parse_sid_file

        sid_file = tmp_path / "bad.sid"
        sid_file.write_bytes(b"JUNK" + bytes(120))

        with pytest.raises(ValueError, match="Not a PSID/RSID"):
            parse_sid_file(sid_file)

    def test_is_pal_flag(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.sid_parser import is_pal, parse_sid_file

        pal_data = _build_psid(flags=0x0004)  # bits 2-3 = 01 → PAL
        pal_file = tmp_path / "pal.sid"
        pal_file.write_bytes(pal_data)
        assert is_pal(parse_sid_file(pal_file)) is True

        ntsc_data = _build_psid(flags=0x0008)  # bits 2-3 = 10 → NTSC
        ntsc_file = tmp_path / "ntsc.sid"
        ntsc_file.write_bytes(ntsc_data)
        assert is_pal(parse_sid_file(ntsc_file)) is False

    def test_speed_for_subtune(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.sid_parser import parse_sid_file, speed_for_subtune

        # speed=0 → all subtunes VBI
        sid_file = tmp_path / "vbi.sid"
        sid_file.write_bytes(_build_psid(speed=0))
        header = parse_sid_file(sid_file)
        assert speed_for_subtune(header, 0) == "VBI"

        # speed=1 → subtune 0 is CIA
        sid_file2 = tmp_path / "cia.sid"
        sid_file2.write_bytes(_build_psid(speed=1))
        header2 = parse_sid_file(sid_file2)
        assert speed_for_subtune(header2, 0) == "CIA"
        assert speed_for_subtune(header2, 1) == "VBI"


# --- Task 1.2: SID CPU / MMU tests ---

class TestSIDInterceptMMU:
    def test_captures_sid_register_writes(self) -> None:
        try:
            from teleclaude.chiptunes.sid_cpu import SIDInterceptMMU
        except ImportError:
            pytest.skip("py65emu not installed")

        ram = bytearray(65536)
        mmu = SIDInterceptMMU(ram)

        mmu.write(0xD400, 0x7F)  # voice 1 freq lo
        mmu.write(0xD401, 0x3A)  # voice 1 freq hi
        mmu.write(0x0000, 0xFF)  # RAM write — should NOT be captured

        writes = mmu.flush_writes()
        assert len(writes) == 2
        assert writes[0] == (0, 0x7F)
        assert writes[1] == (1, 0x3A)

    def test_flush_clears_buffer(self) -> None:
        try:
            from teleclaude.chiptunes.sid_cpu import SIDInterceptMMU
        except ImportError:
            pytest.skip("py65emu not installed")

        ram = bytearray(65536)
        mmu = SIDInterceptMMU(ram)

        mmu.write(0xD400, 0x01)
        mmu.flush_writes()
        assert mmu.flush_writes() == []

    def test_out_of_range_address_not_captured(self) -> None:
        try:
            from teleclaude.chiptunes.sid_cpu import SIDInterceptMMU
        except ImportError:
            pytest.skip("py65emu not installed")

        ram = bytearray(65536)
        mmu = SIDInterceptMMU(ram)

        mmu.write(0xD419, 0x10)  # just outside SID range (0xD418 is last)
        assert mmu.flush_writes() == []


class TestSIDDriver:
    def test_init_and_play_frame(self, tmp_path: Path) -> None:
        try:
            import py65emu  # noqa: F401
            from teleclaude.chiptunes.sid_cpu import SIDDriver
        except ImportError:
            pytest.skip("py65emu not installed")

        from teleclaude.chiptunes.sid_parser import parse_sid_file

        # Minimal PSID: NOP NOP RTS at both init and play addresses
        sid_file = tmp_path / "minimal.sid"
        sid_file.write_bytes(_build_psid(
            load_address=0x1000,
            init_address=0x1000,
            play_address=0x1000,
            payload=b"\xea\xea\x60",  # NOP NOP RTS
        ))
        header = parse_sid_file(sid_file)

        driver = SIDDriver(header)
        driver.init_tune(0)
        writes = driver.play_frame()
        assert isinstance(writes, list)


# --- Task 1.3: SID renderer tests ---

class TestSIDRenderer:
    def test_render_frame_produces_bytes(self) -> None:
        try:
            import pyresidfp  # noqa: F401
            from teleclaude.chiptunes.sid_renderer import SIDRenderer
        except ImportError:
            pytest.skip("pyresidfp not installed")

        renderer = SIDRenderer(sample_rate=22050, pal=True, volume=0.5)
        pcm = renderer.render_frame([], frame_duration_s=0.02)
        assert isinstance(pcm, bytes)
        assert len(pcm) > 0
        assert len(pcm) % 2 == 0  # int16 → 2 bytes per sample

    def test_render_frame_with_writes_produces_non_zero(self) -> None:
        try:
            import pyresidfp  # noqa: F401
            from teleclaude.chiptunes.sid_renderer import SIDRenderer
        except ImportError:
            pytest.skip("pyresidfp not installed")

        renderer = SIDRenderer(sample_rate=22050, pal=True)
        # Write a non-silent voice config
        writes = [
            (0, 0xFF), (1, 0x3A),  # freq
            (5, 0x21),              # attack/decay
            (6, 0xF0),              # sustain/release
            (4, 0x11),              # waveform + gate
        ]
        pcm = renderer.render_frame(writes, frame_duration_s=0.02)
        assert isinstance(pcm, bytes)


# --- Task 1.4/1.5: Player and Manager lifecycle tests ---

class TestChiptunesPlayerLifecycle:
    def test_start_stop_lifecycle(self) -> None:
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            pytest.skip("sounddevice not installed")

        from teleclaude.chiptunes.player import ChiptunesPlayer

        player = ChiptunesPlayer(volume=0.5)
        assert not player.is_playing

        # stop() on an unstarted player should be a no-op
        player.stop()
        assert not player.is_playing

    def test_on_track_end_callback_on_bad_file(self, tmp_path: Path) -> None:
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            pytest.skip("sounddevice not installed")

        from teleclaude.chiptunes.player import ChiptunesPlayer

        called = threading.Event()
        player = ChiptunesPlayer(volume=0.5)
        player.on_track_end = lambda _reason=None: called.set()  # noqa: ARG005

        # Feed an invalid file — should trigger on_track_end
        bad_file = tmp_path / "bad.sid"
        bad_file.write_bytes(b"JUNK" * 10)
        player.play(bad_file)
        assert called.wait(timeout=3.0), "on_track_end was not called for bad file"

    def test_pause_resume(self) -> None:
        from teleclaude.chiptunes.player import ChiptunesPlayer

        player = ChiptunesPlayer()
        player._playing = True
        assert player.is_playing is True
        player.pause()
        assert player._paused is True
        assert player.is_playing is False
        assert player.is_paused is True
        player.resume()
        assert player._paused is False
        assert player.is_playing is True
        assert player.is_paused is False

    def test_pause_blocks_emulation_until_resume(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import teleclaude.chiptunes.player as player_module
        from teleclaude.chiptunes.player import ChiptunesPlayer

        play_frame_started = threading.Event()
        play_frame_calls = 0

        class FakeDriver:
            def __init__(self, _header: object) -> None:
                pass

            def init_tune(self, _subtune: int) -> None:
                pass

            def play_frame(self) -> list[tuple[int, int]]:
                nonlocal play_frame_calls
                play_frame_calls += 1
                play_frame_started.set()
                return []

        class FakeRenderer:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def render_frame(self, _writes: list[tuple[int, int]], _frame_duration_s: float) -> bytes:
                return b"\x00\x00"

        monkeypatch.setattr(player_module, "SIDDriver", FakeDriver)
        monkeypatch.setattr(player_module, "SIDRenderer", FakeRenderer)
        monkeypatch.setattr(player_module, "is_pal", lambda _header: True)
        monkeypatch.setattr(player_module, "speed_for_subtune", lambda _header, _subtune: "VBI")

        player = ChiptunesPlayer()
        player._playing = True
        player.pause()

        worker = threading.Thread(
            target=player._emulation_loop,
            args=(SimpleNamespace(start_song=1),),
            daemon=True,
        )
        worker.start()

        assert not play_frame_started.wait(timeout=0.2), "emulation advanced while paused"

        player.resume()
        assert play_frame_started.wait(timeout=1.0), "emulation did not resume after pause"

        player.stop()
        worker.join(timeout=1.0)

    def test_pause_closes_stream_and_resume_reopens_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import teleclaude.chiptunes.player as player_module
        from teleclaude.chiptunes.player import ChiptunesPlayer

        streams: list[object] = []

        class FakeStream:
            def __init__(self, **_kwargs: object) -> None:
                self.started = False
                self.stopped = False
                self.closed = False
                streams.append(self)

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.stopped = True

            def close(self) -> None:
                self.closed = True

        monkeypatch.setattr(player_module, "sd", SimpleNamespace(RawOutputStream=lambda **kwargs: FakeStream(**kwargs)))

        player = ChiptunesPlayer()
        player._playing = True
        player._stream_blocksize = 256

        assert player._open_stream() is True
        first_stream = streams[-1]
        assert getattr(first_stream, "started") is True

        player.pause()
        assert player.is_paused is True
        assert player._stream is None
        assert getattr(first_stream, "stopped") is True
        assert getattr(first_stream, "closed") is True

        player.resume()
        assert player.is_paused is False
        assert len(streams) == 2
        assert getattr(streams[-1], "started") is True

    def test_prebuffer_does_not_open_stream_while_paused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import teleclaude.chiptunes.player as player_module
        from teleclaude.chiptunes.player import ChiptunesPlayer

        opened = False

        class FakeStream:
            def __init__(self, **_kwargs: object) -> None:
                nonlocal opened
                opened = True

            def start(self) -> None:
                pass

            def stop(self) -> None:
                pass

            def close(self) -> None:
                pass

        monkeypatch.setattr(player_module, "sd", SimpleNamespace(RawOutputStream=lambda **kwargs: FakeStream(**kwargs)))
        monkeypatch.setattr(player_module, "is_pal", lambda _header: True)

        player = ChiptunesPlayer()
        player._playing = True
        player.pause()

        prebuffer_frames = 125
        player._pcm_queue = queue.Queue(maxsize=400)
        for _ in range(prebuffer_frames):
            player._pcm_queue.put_nowait(b"\x00\x00")

        player._start_stream_after_prebuffer(SimpleNamespace())

        assert opened is False
        assert player._stream is None

    def test_enqueue_pcm_does_not_block_for_one_second_when_queue_is_full(self) -> None:
        from teleclaude.chiptunes.player import ChiptunesPlayer

        player = ChiptunesPlayer()
        player._pcm_queue = queue.Queue(maxsize=1)
        player._pcm_queue.put_nowait(b"\x00\x00")
        player.pause()

        started = time.monotonic()
        assert player._enqueue_pcm(b"\x01\x02", frame_duration=0.02) is False
        assert time.monotonic() - started < 0.2

    def test_stream_callback_preserves_fifo_when_chunk_spans_callbacks(self) -> None:
        from teleclaude.chiptunes.player import ChiptunesPlayer

        player = ChiptunesPlayer()
        player._pcm_queue = queue.Queue(maxsize=8)
        player._pcm_queue.put_nowait(b"ABCDEFGH")
        player._pcm_queue.put_nowait(b"IJKLMNOP")
        player._pcm_queue.put_nowait(b"QRSTUVWX")

        out1 = bytearray(12)
        player._stream_callback(out1, frames=6, _time=None, status=None)
        assert bytes(out1) == b"ABCDEFGHIJKL"

        out2 = bytearray(8)
        player._stream_callback(out2, frames=4, _time=None, status=None)
        assert bytes(out2) == b"MNOPQRST"

        out3 = bytearray(8)
        player._stream_callback(out3, frames=4, _time=None, status=None)
        assert bytes(out3) == b"UVWX\x00\x00\x00\x00"

    def test_stream_callback_logs_underflow_status_throttled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import teleclaude.chiptunes.player as player_module
        from teleclaude.chiptunes.player import ChiptunesPlayer

        class FakeStatus:
            output_underflow = True
            output_overflow = False
            input_underflow = False
            input_overflow = False
            priming_output = False

            def __bool__(self) -> bool:
                return True

            def __str__(self) -> str:
                return "output underflow"

        warnings: list[str] = []

        def _warn(msg: str, *args: object) -> None:
            warnings.append(msg % args if args else msg)

        ticks = iter([10.0, 10.5, 13.0])
        monkeypatch.setattr(player_module.time, "monotonic", lambda: next(ticks))
        monkeypatch.setattr(player_module.logger, "warning", _warn)

        player = ChiptunesPlayer()

        player._stream_callback(bytearray(4), frames=2, _time=None, status=FakeStatus())
        player._stream_callback(bytearray(4), frames=2, _time=None, status=FakeStatus())
        player._stream_callback(bytearray(4), frames=2, _time=None, status=FakeStatus())

        assert len(warnings) == 2
        assert "output_underflow" in warnings[0]
        assert "suppressed=1" in warnings[1]


class TestChiptunesManagerLifecycle:
    def test_start_stop(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.manager import ChiptunesManager

        # Empty music_dir — manager should still start without crashing
        music_dir = tmp_path / "music"
        music_dir.mkdir()

        manager = ChiptunesManager(music_dir, volume=0.3)
        assert not manager.enabled

        manager.start()
        assert manager.enabled

        manager.stop()
        assert not manager.enabled

    def test_pause_resume_when_stopped(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.manager import ChiptunesManager

        manager = ChiptunesManager(tmp_path)
        manager.pause()  # Should not raise even when player is None
        manager.resume()

    def test_discover_filters_rsid(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.manager import ChiptunesManager

        music_dir = tmp_path / "music"
        music_dir.mkdir()

        psid_file = music_dir / "tune.sid"
        psid_file.write_bytes(_build_psid())

        rsid_file = music_dir / "rsid_tune.sid"
        rsid_file.write_bytes(b"RSID" + _build_psid()[4:])

        manager = ChiptunesManager(music_dir, volume=0.5)
        tracks = manager._discover_tracks()

        assert psid_file in tracks
        assert rsid_file not in tracks


# --- Task 2.1: RuntimeSettings chiptunes patch tests ---

class TestRuntimeSettingsChiptunes:
    @pytest.fixture
    def tts_manager(self) -> MagicMock:
        mgr = MagicMock()
        mgr.enabled = False
        return mgr

    @pytest.fixture
    def chiptunes_manager(self) -> MagicMock:
        mgr = MagicMock()
        mgr.enabled = False
        mgr.is_paused = False
        mgr.is_playing = False
        return mgr

    @pytest.fixture
    def settings_json(self, tmp_path: Path) -> Path:
        p = tmp_path / "runtime-settings.json"
        p.write_text('{"tts": {"enabled": false}}')
        return p

    def test_set_chiptunes_paused_persists_playback_state(
        self,
        settings_json: Path,
        tts_manager: MagicMock,
        chiptunes_manager: MagicMock,
    ) -> None:
        from teleclaude.config.runtime_settings import ChiptunesRuntimeState, RuntimeSettings

        chiptunes_manager.enabled = True
        chiptunes_manager.is_playing = True
        chiptunes_manager.capture_runtime_state.return_value = ChiptunesRuntimeState(
            playback="paused",
            track_path="/music/demo.sid",
            position_seconds=12.5,
            history=["/music/demo.sid"],
            history_index=0,
        )
        settings = RuntimeSettings(settings_json, tts_manager, chiptunes_manager)
        result = settings.set_chiptunes_paused(True)

        assert result.chiptunes.playback == "paused"
        assert result.chiptunes.track_path == "/music/demo.sid"
        assert result.chiptunes.position_seconds == 12.5
        tts_manager.on_chiptunes_user_pause.assert_called_once()
        chiptunes_manager.pause.assert_called_once()

    def test_parse_patch_rejects_chiptunes_key(self) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        with pytest.raises(ValueError, match="Unknown settings keys"):
            RuntimeSettings.parse_patch({"chiptunes": {"enabled": True}})

    def test_parse_patch_rejects_unknown_top_key(self) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        with pytest.raises(ValueError, match="Unknown settings keys"):
            RuntimeSettings.parse_patch({"music": {"enabled": True}})

    def test_get_state_includes_chiptunes(
        self,
        settings_json: Path,
        tts_manager: MagicMock,
        chiptunes_manager: MagicMock,
    ) -> None:
        from teleclaude.config.runtime_settings import ChiptunesRuntimeState, RuntimeSettings

        chiptunes_manager.capture_runtime_state.return_value = ChiptunesRuntimeState(
            playback="cold",
            track_path="",
            position_seconds=0.0,
            history=[],
            history_index=-1,
        )
        settings = RuntimeSettings(settings_json, tts_manager, chiptunes_manager)
        state = settings.get_state()
        assert state.chiptunes.playback == "cold"
        assert state.chiptunes.position_seconds == 0.0


# --- Task 2.3: API patch validation for chiptunes key ---

class TestAPIChiptunesPatch:
    def test_settings_patch_dto_rejects_chiptunes(self) -> None:
        from pydantic import ValidationError

        from teleclaude.api_models import SettingsPatchDTO

        with pytest.raises(ValidationError):
            SettingsPatchDTO(chiptunes={"enabled": True})

    def test_settings_dto_contains_tts_only(self) -> None:
        from teleclaude.api_models import SettingsDTO, TTSSettingsDTO

        dto = SettingsDTO(tts=TTSSettingsDTO(enabled=False))
        assert dto.tts.enabled is False


# --- Task 4.1: TTS + chiptunes coexistence (pause/resume) ---

class TestTTSChiptunesCoexistence:
    @pytest.mark.asyncio
    async def test_tts_queue_holds_music_pause_until_queue_drains(self) -> None:
        from teleclaude.tts.manager import TTSManager
        from teleclaude.core.voice_assignment import VoiceConfig

        mgr = TTSManager.__new__(TTSManager)
        mgr.enabled = True
        mgr.tts_config = MagicMock()
        mgr.tts_config.enabled = True

        chiptunes = MagicMock()
        chiptunes.enabled = True
        chiptunes.is_playing = True
        mgr.set_chiptunes_manager(chiptunes)

        voice = VoiceConfig(service_name="kokoro", voice="bm_lewis")
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def fake_run(
            text: str,
            service_chain: list[tuple[str, str | None]],
            session_id: str,
        ) -> tuple[bool, str | None, str | None]:
            assert service_chain == [("kokoro", "bm_lewis")]
            if text == "first":
                first_started.set()
                await release_first.wait()
            return True, "kokoro", "bm_lewis"

        with (
            patch("teleclaude.tts.manager.db") as mock_db,
            patch.object(mgr, "_get_or_assign_voice", AsyncMock(return_value=voice)),
            patch("teleclaude.tts.manager.run_tts_with_lock_async", side_effect=fake_run),
        ):
            mock_db.get_session = AsyncMock(return_value=MagicMock(last_input_origin="terminal"))

            assert await mgr.speak("first", session_id="sess-1") is True
            await first_started.wait()
            assert await mgr.speak("second", session_id="sess-1") is True

            chiptunes.pause.assert_called_once()
            chiptunes.resume.assert_not_called()

            release_first.set()
            assert mgr._speech_queue is not None
            await mgr._speech_queue.join()

        chiptunes.pause.assert_called_once()
        chiptunes.resume.assert_called_once()

    def test_set_chiptunes_manager(self) -> None:
        from teleclaude.tts.manager import TTSManager

        mgr = TTSManager.__new__(TTSManager)
        mgr._chiptunes_manager = None
        chiptunes = MagicMock()
        mgr.set_chiptunes_manager(chiptunes)
        assert mgr._chiptunes_manager is chiptunes

    def test_chiptunes_state_change_reasserts_audio_focus(self) -> None:
        from teleclaude.tts.manager import TTSManager

        mgr = TTSManager.__new__(TTSManager)
        chiptunes = MagicMock()
        chiptunes.enabled = True
        chiptunes.is_playing = True
        mgr.set_chiptunes_manager(chiptunes)

        mgr._audio_focus.claim_foreground()
        chiptunes.pause.reset_mock()

        mgr.on_chiptunes_state_change()

        chiptunes.pause.assert_called_once()

    def test_audio_focus_does_not_resume_user_paused_music(self) -> None:
        from teleclaude.tts.audio_focus import AudioFocusCoordinator

        chiptunes = MagicMock()
        chiptunes.enabled = True
        chiptunes.is_playing = False
        chiptunes.is_paused = True

        focus = AudioFocusCoordinator()
        focus.set_chiptunes_manager(chiptunes)

        focus.claim_foreground()
        focus.release_foreground()

        chiptunes.pause.assert_not_called()
        chiptunes.resume.assert_not_called()

    def test_chiptunes_state_change_ignores_already_paused_music(self) -> None:
        from teleclaude.tts.audio_focus import AudioFocusCoordinator

        chiptunes = MagicMock()
        chiptunes.enabled = True
        chiptunes.is_playing = True
        chiptunes.is_paused = False

        focus = AudioFocusCoordinator()
        focus.set_chiptunes_manager(chiptunes)

        focus.claim_foreground()
        chiptunes.pause.assert_called_once()

        chiptunes.pause.reset_mock()
        chiptunes.is_playing = False
        chiptunes.is_paused = True

        focus.on_background_state_change()

        chiptunes.pause.assert_not_called()

    def test_audio_focus_user_pause_cancels_pending_resume(self) -> None:
        from teleclaude.tts.audio_focus import AudioFocusCoordinator

        chiptunes = MagicMock()
        chiptunes.enabled = True
        chiptunes.is_playing = True
        chiptunes.is_paused = False

        focus = AudioFocusCoordinator()
        focus.set_chiptunes_manager(chiptunes)

        focus.claim_foreground()
        chiptunes.pause.assert_called_once()

        focus.cancel_background_resume()
        focus.release_foreground()

        chiptunes.resume.assert_not_called()


# --- Worker track history and navigation ---


class TestWorkerTrackHistory:
    def _make_worker(self, tracks: list[Path]) -> object:
        from teleclaude.chiptunes.worker import _Worker

        track_iter = iter(tracks)

        def _pick() -> Path | None:
            return next(track_iter, None)

        worker = _Worker(pick_random_track=_pick, volume=0.0)
        worker._enabled = True
        # Patch _play_track to record calls without side effects
        worker._played: list[Path] = []

        def _fake_play(track: Path) -> None:
            worker._played.append(track)

        worker._play_track = _fake_play  # type: ignore[assignment]
        return worker

    def test_play_next_appends_to_history(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "a.sid", tmp_path / "b.sid"]
        worker = self._make_worker(tracks)

        worker._play_next()
        assert worker._history == [tracks[0]]
        assert worker._history_index == 0

        worker._play_next()
        assert worker._history == [tracks[0], tracks[1]]
        assert worker._history_index == 1

    def test_play_prev_goes_back(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "a.sid", tmp_path / "b.sid"]
        worker = self._make_worker(tracks)

        worker._play_next()
        worker._play_next()
        worker._play_prev()

        assert worker._history_index == 0
        assert worker._played[-1] == tracks[0]

    def test_play_prev_at_start_is_noop(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "a.sid"]
        worker = self._make_worker(tracks)

        worker._play_next()
        played_count = len(worker._played)
        worker._play_prev()  # already at beginning

        assert len(worker._played) == played_count  # no additional play

    def test_play_next_replays_history_before_end(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "a.sid", tmp_path / "b.sid", tmp_path / "c.sid"]
        worker = self._make_worker(tracks)

        worker._play_next()  # a
        worker._play_next()  # b
        worker._play_prev()  # back to a
        worker._play_next()  # forward to b (from history, not new)

        assert worker._history == [tracks[0], tracks[1]]  # no c added yet
        assert worker._history_index == 1
        assert worker._played[-1] == tracks[1]

    def test_handle_cmd_next(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "x.sid"]
        worker = self._make_worker(tracks)

        worker.handle_cmd({"cmd": "next"})
        import time
        time.sleep(0.05)  # wait for daemon thread

        assert len(worker._history) == 1

    def test_handle_cmd_prev_noop_at_start(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "x.sid"]
        worker = self._make_worker(tracks)

        worker._play_next()
        played_before = len(worker._played)
        worker.handle_cmd({"cmd": "prev"})
        import time
        time.sleep(0.05)

        assert len(worker._played) == played_before  # no extra play at beginning

    def test_handle_cmd_unknown_ignored(self, tmp_path: Path) -> None:
        tracks = [tmp_path / "x.sid"]
        worker = self._make_worker(tracks)

        worker.handle_cmd({"cmd": "shuffle"})  # unknown — no-op

    def test_pause_request_is_reapplied_to_new_track(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import teleclaude.chiptunes.worker as worker_module

        events: list[str] = []

        class FakePlayer:
            def __init__(self, volume: float) -> None:
                self.volume = volume
                self.on_track_end = None
                self.is_playing = True
                self.is_paused = False
                self.playback_position_seconds = 0.0

            def stop(self) -> None:
                events.append("stop")

            def play(
                self,
                track: Path,
                *,
                start_paused: bool = False,
                start_position_seconds: float = 0.0,
            ) -> None:
                self.playback_position_seconds = start_position_seconds
                events.append(f"play:{track.name}:{start_paused}")

            def pause(self) -> None:
                self.is_paused = True
                events.append("pause")

            def resume(self) -> None:
                self.is_paused = False
                events.append("resume")

        monkeypatch.setattr(worker_module, "ChiptunesPlayer", FakePlayer)

        track = tmp_path / "demo.sid"
        track.write_bytes(_build_psid())
        worker = worker_module._Worker(pick_random_track=lambda: track, volume=0.2)
        worker._enabled = True
        worker.pause()

        worker._play_track(track)

        assert events == [f"play:{track.name}:True"]
        assert worker.is_paused is True

    def test_pause_is_idempotent(self) -> None:
        from teleclaude.chiptunes.worker import _Worker

        events: list[str] = []

        class FakePlayer:
            def __init__(self) -> None:
                self.is_paused = False
                self.playback_position_seconds = 0.0

            def pause(self) -> None:
                self.is_paused = True
                events.append("pause")

        worker = _Worker(pick_random_track=lambda: None, volume=0.0, on_state_change=lambda: events.append("state"))
        worker._player = FakePlayer()

        worker.pause()
        worker.pause()

        assert events == ["pause", "state"]

    def test_on_track_end_does_not_auto_advance_on_stream_open_failure(self, tmp_path: Path) -> None:
        from types import SimpleNamespace
        from teleclaude.chiptunes.worker import _Worker

        track = tmp_path / "bad.sid"
        track.write_bytes(_build_psid())
        events: list[str] = []
        worker = _Worker(pick_random_track=lambda: track, volume=0.0)
        worker._enabled = True
        worker._player = SimpleNamespace(track_end_reason="stream_open_failed")
        worker._play_next = lambda: events.append("next")
        worker.on_state_change = lambda: events.append("state")

        worker._on_track_end()

        assert events == ["state"]

    def test_on_track_end_advances_on_normal_completion(self, tmp_path: Path) -> None:
        from types import SimpleNamespace
        from teleclaude.chiptunes.worker import _Worker

        track = tmp_path / "ok.sid"
        track.write_bytes(_build_psid())
        events: list[str] = []
        worker = _Worker(pick_random_track=lambda: track, volume=0.0)
        worker._enabled = True
        worker._player = SimpleNamespace(track_end_reason="track_completed")
        worker._play_next = lambda: events.append("next")

        worker._on_track_end()

        assert events == ["next"]


# --- Manager next_track / prev_track proxy methods ---


class TestManagerNavigation:
    def test_next_track_delegates_to_worker(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.manager import ChiptunesManager

        manager = ChiptunesManager(tmp_path)
        manager._worker.handle_cmd = MagicMock()  # type: ignore[method-assign]

        manager.next_track()
        manager._worker.handle_cmd.assert_called_once_with({"cmd": "next"})

    def test_prev_track_delegates_to_worker(self, tmp_path: Path) -> None:
        from teleclaude.chiptunes.manager import ChiptunesManager

        manager = ChiptunesManager(tmp_path)
        manager._worker.handle_cmd = MagicMock()  # type: ignore[method-assign]

        manager.prev_track()
        manager._worker.handle_cmd.assert_called_once_with({"cmd": "prev"})


# --- Favorites persistence ---


class TestFavorites:
    def test_save_and_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        fav_path = tmp_path / "chiptunes-favorites.json"
        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

        fav_mod.save_favorite("Test Tune", "/music/test.sid")
        loaded = fav_mod.load_favorites()

        assert len(loaded) == 1
        assert loaded[0]["track_name"] == "Test Tune"
        assert loaded[0]["sid_path"] == "/music/test.sid"
        assert "saved_at" in loaded[0]

    def test_is_favorited_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        fav_path = tmp_path / "chiptunes-favorites.json"
        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

        fav_mod.save_favorite("Track A", "/music/a.sid")
        assert fav_mod.is_favorited("/music/a.sid") is True

    def test_is_favorited_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        fav_path = tmp_path / "chiptunes-favorites.json"
        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

        assert fav_mod.is_favorited("/music/missing.sid") is False

    def test_deduplication(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        fav_path = tmp_path / "chiptunes-favorites.json"
        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

        fav_mod.save_favorite("Track A", "/music/a.sid")
        fav_mod.save_favorite("Track A Again", "/music/a.sid")  # duplicate sid_path

        assert len(fav_mod.load_favorites()) == 1

    def test_remove_favorite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        fav_path = tmp_path / "chiptunes-favorites.json"
        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

        fav_mod.save_favorite("Track A", "/music/a.sid")
        removed = fav_mod.remove_favorite("/music/a.sid")

        assert removed is True
        assert fav_mod.load_favorites() == []
        assert fav_mod.is_favorited("/music/a.sid") is False

    def test_load_returns_empty_on_missing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", tmp_path / "nonexistent.json")
        assert fav_mod.load_favorites() == []

    def test_load_returns_empty_on_malformed_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from teleclaude.chiptunes import favorites as fav_mod

        fav_path = tmp_path / "bad.json"
        fav_path.write_text("{not valid json")
        monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

        assert fav_mod.load_favorites() == []


# --- ChiptunesTrackEventDTO sid_path field ---


class TestChiptunesTrackEventDTO:
    def test_default_sid_path_is_empty(self) -> None:
        from teleclaude.api_models import ChiptunesTrackEventDTO

        dto = ChiptunesTrackEventDTO(track="Cool Tune")
        assert dto.sid_path == ""

    def test_explicit_sid_path(self) -> None:
        from teleclaude.api_models import ChiptunesTrackEventDTO

        dto = ChiptunesTrackEventDTO(track="Cool Tune", sid_path="/music/cool.sid")
        assert dto.sid_path == "/music/cool.sid"
        assert dto.event == "chiptunes_track"

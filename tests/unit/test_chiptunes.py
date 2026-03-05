"""Unit tests for the chiptunes SID playback feature."""

from __future__ import annotations

import struct
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

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

        mmu.cpu_write(0xD400, 0x7F)  # voice 1 freq lo
        mmu.cpu_write(0xD401, 0x3A)  # voice 1 freq hi
        mmu.cpu_write(0x0000, 0xFF)  # RAM write — should NOT be captured

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

        mmu.cpu_write(0xD400, 0x01)
        mmu.flush_writes()
        assert mmu.flush_writes() == []

    def test_out_of_range_address_not_captured(self) -> None:
        try:
            from teleclaude.chiptunes.sid_cpu import SIDInterceptMMU
        except ImportError:
            pytest.skip("py65emu not installed")

        ram = bytearray(65536)
        mmu = SIDInterceptMMU(ram)

        mmu.cpu_write(0xD419, 0x10)  # just outside SID range (0xD418 is last)
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
        player.on_track_end = called.set

        # Feed an invalid file — should trigger on_track_end
        bad_file = tmp_path / "bad.sid"
        bad_file.write_bytes(b"JUNK" * 10)
        player.play(bad_file)
        assert called.wait(timeout=3.0), "on_track_end was not called for bad file"

    def test_pause_resume(self) -> None:
        from teleclaude.chiptunes.player import ChiptunesPlayer

        player = ChiptunesPlayer()
        player.pause()
        assert player._paused is True
        player.resume()
        assert player._paused is False


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

        manager = ChiptunesManager(music_dir)
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
        return mgr

    @pytest.fixture
    def config_yml(self, tmp_path: Path) -> Path:
        p = tmp_path / "config.yml"
        p.write_text("tts:\n  enabled: false\nchiptunes:\n  enabled: false\n")
        return p

    def test_patch_chiptunes_enabled(
        self,
        config_yml: Path,
        tts_manager: MagicMock,
        chiptunes_manager: MagicMock,
    ) -> None:
        from teleclaude.config.runtime_settings import ChiptunesSettingsPatch, RuntimeSettings, SettingsPatch

        settings = RuntimeSettings(config_yml, tts_manager, chiptunes_manager)
        result = settings.patch(SettingsPatch(chiptunes=ChiptunesSettingsPatch(enabled=True)))

        assert result.chiptunes.enabled is True
        chiptunes_manager.start.assert_called_once()

    def test_patch_chiptunes_disabled(
        self,
        config_yml: Path,
        tts_manager: MagicMock,
        chiptunes_manager: MagicMock,
    ) -> None:
        from teleclaude.config.runtime_settings import ChiptunesSettingsPatch, RuntimeSettings, SettingsPatch

        settings = RuntimeSettings(config_yml, tts_manager, chiptunes_manager)
        settings.patch(SettingsPatch(chiptunes=ChiptunesSettingsPatch(enabled=False)))

        chiptunes_manager.stop.assert_called_once()

    def test_parse_patch_chiptunes_valid(self) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        result = RuntimeSettings.parse_patch({"chiptunes": {"enabled": True}})
        assert result.chiptunes is not None
        assert result.chiptunes.enabled is True

    def test_parse_patch_chiptunes_unknown_key(self) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        with pytest.raises(ValueError, match="Unknown chiptunes keys"):
            RuntimeSettings.parse_patch({"chiptunes": {"enabled": True, "volume": 0.8}})

    def test_parse_patch_rejects_unknown_top_key(self) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        with pytest.raises(ValueError, match="Unknown settings keys"):
            RuntimeSettings.parse_patch({"music": {"enabled": True}})

    def test_parse_patch_chiptunes_requires_boolean(self) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        with pytest.raises(ValueError, match="chiptunes.enabled must be a boolean"):
            RuntimeSettings.parse_patch({"chiptunes": {"enabled": "yes"}})

    def test_get_state_includes_chiptunes(
        self,
        config_yml: Path,
        tts_manager: MagicMock,
        chiptunes_manager: MagicMock,
    ) -> None:
        from teleclaude.config.runtime_settings import RuntimeSettings

        chiptunes_manager.enabled = True
        settings = RuntimeSettings(config_yml, tts_manager, chiptunes_manager)
        state = settings.get_state()
        assert state.chiptunes.enabled is True


# --- Task 2.3: API patch validation for chiptunes key ---

class TestAPIChiptunesPatch:
    def test_settings_patch_dto_accepts_chiptunes(self) -> None:
        from teleclaude.api_models import ChiptunesSettingsPatchDTO, SettingsPatchDTO

        dto = SettingsPatchDTO(chiptunes=ChiptunesSettingsPatchDTO(enabled=True))
        assert dto.chiptunes is not None
        assert dto.chiptunes.enabled is True

    def test_settings_dto_includes_chiptunes(self) -> None:
        from teleclaude.api_models import ChiptunesSettingsDTO, SettingsDTO, TTSSettingsDTO

        dto = SettingsDTO(
            tts=TTSSettingsDTO(enabled=False),
            chiptunes=ChiptunesSettingsDTO(enabled=True),
        )
        assert dto.chiptunes.enabled is True


# --- Task 4.1: TTS + chiptunes coexistence (pause/resume) ---

class TestTTSChiptunesCoexistence:
    def test_trigger_event_pauses_chiptunes(self) -> None:
        from teleclaude.tts.manager import TTSManager

        mgr = TTSManager.__new__(TTSManager)
        mgr.enabled = True
        mgr.tts_config = MagicMock()
        mgr.tts_config.enabled = True

        chiptunes = MagicMock()
        chiptunes.is_playing = True
        mgr._chiptunes_manager = chiptunes

        # Simulate the pause call that happens before TTS queuing
        if mgr._chiptunes_manager is not None and mgr._chiptunes_manager.is_playing:
            mgr._chiptunes_manager.pause()

        chiptunes.pause.assert_called_once()

    def test_set_chiptunes_manager(self) -> None:
        from teleclaude.tts.manager import TTSManager

        mgr = TTSManager.__new__(TTSManager)
        mgr._chiptunes_manager = None
        chiptunes = MagicMock()
        mgr.set_chiptunes_manager(chiptunes)
        assert mgr._chiptunes_manager is chiptunes

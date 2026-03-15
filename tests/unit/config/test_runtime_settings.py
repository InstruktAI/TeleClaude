"""Characterization tests for teleclaude.config.runtime_settings."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from teleclaude.config.runtime_settings import (
    ChiptunesRuntimeState,
    RuntimeSettings,
    SettingsPatch,
    TTSSettingsPatch,
)


class StubTTSManager:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self.user_pause_calls = 0

    def on_chiptunes_user_pause(self) -> None:
        self.user_pause_calls += 1


class StubChiptunesManager:
    def __init__(
        self,
        *,
        enabled: bool = False,
        is_playing: bool = False,
        runtime_state: ChiptunesRuntimeState | None = None,
    ) -> None:
        self.enabled = enabled
        self.is_playing = is_playing
        self.runtime_state = runtime_state or ChiptunesRuntimeState()
        self.restore_calls: list[ChiptunesRuntimeState] = []
        self.start_calls: list[bool] = []
        self.start_from_state_calls: list[ChiptunesRuntimeState] = []
        self.pause_calls = 0
        self.resume_calls = 0
        self.enqueue_calls: list[tuple[str, str]] = []

    def restore_runtime_state(self, state: ChiptunesRuntimeState) -> None:
        self.restore_calls.append(copy.deepcopy(state))

    def start(self, *, paused: bool = False) -> None:
        self.enabled = True
        self.start_calls.append(paused)

    def start_from_runtime_state(self, state: ChiptunesRuntimeState) -> None:
        self.enabled = True
        self.start_from_state_calls.append(copy.deepcopy(state))

    def pause(self) -> None:
        self.is_playing = False
        self.pause_calls += 1

    def resume(self) -> None:
        self.is_playing = True
        self.resume_calls += 1

    def capture_runtime_state(self) -> ChiptunesRuntimeState:
        return copy.deepcopy(self.runtime_state)

    def enqueue_command(self, command_id: str, action: str) -> None:
        self.enabled = True
        self.enqueue_calls.append((command_id, action))


def _make_settings(
    tmp_path: Path,
    *,
    payload: Mapping[str, object] | None = None,
    tts_enabled: bool = False,
    chiptunes_manager: StubChiptunesManager | None = None,
) -> tuple[RuntimeSettings, StubTTSManager, Path]:
    settings_path = tmp_path / "state" / "runtime-settings.json"
    if payload is not None:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload), encoding="utf-8")
    tts_manager = StubTTSManager(enabled=tts_enabled)
    settings = RuntimeSettings(settings_path, tts_manager, chiptunes_manager)
    return settings, tts_manager, settings_path


class TestParsePatch:
    @pytest.mark.unit
    def test_parses_valid_tts_patch(self) -> None:
        patch_payload = RuntimeSettings.parse_patch({"tts": {"enabled": True}})
        assert patch_payload == SettingsPatch(tts=TTSSettingsPatch(enabled=True))

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            (None, "Expected JSON object"),
            ({"unknown": True}, "Unknown settings keys"),
            ({"tts": "on"}, "tts must be an object"),
            ({"tts": {"volume": 1}}, "Unknown tts keys"),
            ({"tts": {"enabled": "yes"}}, "tts.enabled must be a boolean"),
        ],
    )
    def test_rejects_invalid_payloads(self, raw: object, message: str) -> None:
        with pytest.raises(ValueError) as exc_info:
            RuntimeSettings.parse_patch(raw)

        assert message in str(exc_info.value)


class TestRuntimeSettingsLoading:
    @pytest.mark.unit
    def test_load_from_disk_applies_tts_and_sanitizes_loading_state(self, tmp_path: Path) -> None:
        payload = {
            "tts": {"enabled": True},
            "chiptunes": {
                "playback": "loading",
                "track_path": "music/song.sid",
                "position_seconds": -5,
                "history": ["first.sid", 3, "second.sid"],
                "history_index": 4,
                "pending_command_id": "cmd-123",
                "pending_action": "next",
                "state_version": -7,
            },
        }

        settings, tts_manager, _ = _make_settings(tmp_path, payload=payload)
        state = settings.get_state()

        assert state.tts.enabled is True
        assert tts_manager.enabled is True
        assert state.chiptunes.playback == "cold"
        assert state.chiptunes.track_path == "music/song.sid"
        assert state.chiptunes.position_seconds == 0.0
        assert state.chiptunes.history == ["first.sid", "second.sid"]
        assert state.chiptunes.history_index == 4
        assert state.chiptunes.pending_command_id == ""
        assert state.chiptunes.pending_action == ""
        assert settings.chiptunes_state_version == 0

    @pytest.mark.unit
    def test_bootstrap_chiptunes_restores_and_starts_when_state_is_playing(self, tmp_path: Path) -> None:
        payload = {
            "chiptunes": {
                "playback": "playing",
                "track_path": "music/song.sid",
                "position_seconds": 12.5,
            }
        }
        manager = StubChiptunesManager()
        settings, _, _ = _make_settings(tmp_path, payload=payload, chiptunes_manager=manager)

        settings.bootstrap_chiptunes()

        assert len(manager.restore_calls) == 1
        assert manager.restore_calls[0].track_path == "music/song.sid"
        assert len(manager.start_from_state_calls) == 1
        assert manager.start_from_state_calls[0].position_seconds == 12.5


class TestRuntimeSettingsMutation:
    @pytest.mark.unit
    def test_patch_updates_tts_state_and_manager(self, tmp_path: Path) -> None:
        settings, tts_manager, _ = _make_settings(tmp_path, tts_enabled=False)

        state = settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=True)))

        assert state.tts.enabled is True
        assert tts_manager.enabled is True

    @pytest.mark.unit
    def test_patch_without_mutable_fields_raises_value_error(self, tmp_path: Path) -> None:
        settings, _, _ = _make_settings(tmp_path)

        with pytest.raises(ValueError, match="No mutable settings in patch"):
            settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=None)))

    @pytest.mark.unit
    def test_set_chiptunes_paused_pauses_active_playback(self, tmp_path: Path) -> None:
        runtime_state = ChiptunesRuntimeState(playback="playing", track_path="music/song.sid", position_seconds=8.5)
        manager = StubChiptunesManager(is_playing=True, runtime_state=runtime_state)
        settings, tts_manager, _ = _make_settings(tmp_path, chiptunes_manager=manager)

        state = settings.set_chiptunes_paused(True)

        assert tts_manager.user_pause_calls == 1
        assert manager.pause_calls == 1
        assert state.chiptunes.playback == "paused"
        assert state.chiptunes.track_path == "music/song.sid"
        assert settings.chiptunes_state_version == 1

    @pytest.mark.unit
    def test_set_chiptunes_paused_resumes_loaded_manager(self, tmp_path: Path) -> None:
        runtime_state = ChiptunesRuntimeState(playback="paused", track_path="music/song.sid", position_seconds=14.0)
        manager = StubChiptunesManager(enabled=True, runtime_state=runtime_state)
        settings, _, _ = _make_settings(tmp_path, chiptunes_manager=manager)

        state = settings.set_chiptunes_paused(False)

        assert manager.resume_calls == 1
        assert manager.start_calls == []
        assert manager.start_from_state_calls == []
        assert state.chiptunes.playback == "playing"
        assert settings.chiptunes_state_version == 1

    @pytest.mark.unit
    def test_set_chiptunes_paused_cold_starts_when_no_track_is_persisted(self, tmp_path: Path) -> None:
        runtime_state = ChiptunesRuntimeState(playback="paused", track_path="music/fresh.sid", position_seconds=0.0)
        manager = StubChiptunesManager(enabled=False, runtime_state=runtime_state)
        settings, _, _ = _make_settings(tmp_path, chiptunes_manager=manager)

        state = settings.set_chiptunes_paused(False)

        assert manager.start_calls == [False]
        assert manager.start_from_state_calls == []
        assert state.chiptunes.playback == "playing"

    @pytest.mark.unit
    def test_set_chiptunes_paused_starts_from_saved_track_when_disabled(self, tmp_path: Path) -> None:
        runtime_state = ChiptunesRuntimeState(playback="paused", track_path="music/saved.sid", position_seconds=21.0)
        manager = StubChiptunesManager(enabled=False, runtime_state=runtime_state)
        settings, _, _ = _make_settings(tmp_path, chiptunes_manager=manager)
        settings.get_state().chiptunes.track_path = "music/saved.sid"
        settings.get_state().chiptunes.position_seconds = 21.0

        state = settings.set_chiptunes_paused(False)

        assert manager.start_calls == []
        assert len(manager.start_from_state_calls) == 1
        assert manager.start_from_state_calls[0].track_path == "music/saved.sid"
        assert state.chiptunes.playback == "playing"

    @pytest.mark.unit
    def test_issue_chiptunes_command_sets_pending_fields_and_enqueues(self, tmp_path: Path) -> None:
        manager = StubChiptunesManager()
        settings, _, _ = _make_settings(tmp_path, chiptunes_manager=manager)

        with patch("teleclaude.config.runtime_settings.uuid4", return_value=SimpleNamespace(hex="abc123")):
            command_id = settings.issue_chiptunes_command("next")

        assert command_id == "abc123"
        assert settings.get_state().chiptunes.pending_command_id == "abc123"
        assert settings.get_state().chiptunes.pending_action == "next"
        assert settings.chiptunes_state_version == 1
        assert manager.enqueue_calls == [("abc123", "next")]

    @pytest.mark.unit
    def test_issue_chiptunes_command_requires_manager(self, tmp_path: Path) -> None:
        settings, _, _ = _make_settings(tmp_path)

        with pytest.raises(ValueError, match="Chiptunes manager not available"):
            settings.issue_chiptunes_command("pause")

    @pytest.mark.unit
    def test_sync_chiptunes_state_mirrors_manager_state(self, tmp_path: Path) -> None:
        runtime_state = ChiptunesRuntimeState(playback="paused", track_path="music/song.sid", position_seconds=5.0)
        manager = StubChiptunesManager(runtime_state=runtime_state)
        settings, _, _ = _make_settings(tmp_path, chiptunes_manager=manager)

        settings.sync_chiptunes_state()

        assert settings.get_state().chiptunes.track_path == "music/song.sid"
        assert settings.get_state().chiptunes.position_seconds == 5.0
        assert settings.chiptunes_state_version == 1

    @pytest.mark.unit
    def test_flush_to_disk_writes_current_state(self, tmp_path: Path) -> None:
        settings, _, settings_path = _make_settings(tmp_path)
        settings.get_state().tts.enabled = True
        settings.get_state().chiptunes = ChiptunesRuntimeState(
            playback="paused",
            track_path="music/song.sid",
            position_seconds=3.5,
            history=["a.sid"],
            history_index=0,
            pending_command_id="cmd-1",
            pending_action="pause",
        )
        settings.get_state().chiptunes_state_version = 9

        asyncio.run(settings._flush_to_disk())
        payload = json.loads(settings_path.read_text(encoding="utf-8"))

        assert payload == {
            "chiptunes": {
                "history": ["a.sid"],
                "history_index": 0,
                "pending_action": "pause",
                "pending_command_id": "cmd-1",
                "playback": "paused",
                "position_seconds": 3.5,
                "state_version": 9,
                "track_path": "music/song.sid",
            },
            "tts": {"enabled": True},
        }

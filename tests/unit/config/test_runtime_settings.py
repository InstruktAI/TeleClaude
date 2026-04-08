"""Characterization tests for teleclaude.config.runtime_settings."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from teleclaude.config.runtime_settings import (
    RuntimeSettings,
    SettingsPatch,
    TTSSettingsPatch,
)


class StubTTSManager:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled


def _make_settings(
    tmp_path: Path,
    *,
    payload: Mapping[str, object] | None = None,
    tts_enabled: bool = False,
) -> tuple[RuntimeSettings, StubTTSManager, Path]:
    settings_path = tmp_path / "state" / "runtime-settings.json"
    if payload is not None:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload), encoding="utf-8")
    tts_manager = StubTTSManager(enabled=tts_enabled)
    settings = RuntimeSettings(settings_path, tts_manager)
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
    def test_load_from_disk_applies_tts(self, tmp_path: Path) -> None:
        payload = {"tts": {"enabled": True}}

        settings, tts_manager, _ = _make_settings(tmp_path, payload=payload)
        state = settings.get_state()

        assert state.tts.enabled is True
        assert tts_manager.enabled is True


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
    def test_flush_to_disk_writes_current_state(self, tmp_path: Path) -> None:
        settings, _, settings_path = _make_settings(tmp_path)
        settings.get_state().tts.enabled = True

        asyncio.run(settings._flush_to_disk())
        payload = json.loads(settings_path.read_text(encoding="utf-8"))

        assert payload == {
            "tts": {"enabled": True},
        }

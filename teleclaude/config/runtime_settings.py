"""Mutable runtime settings with debounced JSON persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.tts.manager import TTSManager

logger = get_logger(__name__)

FLUSH_DELAY_S = 0.5


@dataclass
class TTSSettings:
    """TTS section of mutable settings."""

    enabled: bool = False


@dataclass
class SettingsState:
    """Full mutable runtime state."""

    tts: TTSSettings


@dataclass
class TTSSettingsPatch:
    """Patch payload for TTS settings. All fields optional."""

    enabled: bool | None = None


@dataclass
class SettingsPatch:
    """Typed patch payload for settings updates."""

    tts: TTSSettingsPatch | None = None


class RuntimeSettings:
    """In-memory mutable runtime settings layer with debounced JSON persistence."""

    def __init__(
        self,
        settings_path: Path,
        tts_manager: TTSManager,
    ) -> None:
        self._settings_path = settings_path
        self._tts_manager = tts_manager
        self._state = SettingsState(tts=TTSSettings(enabled=tts_manager.enabled))
        self._flush_task: asyncio.Task[None] | None = None
        self._load_from_disk()

    @property
    def settings_path(self) -> Path:
        """Path of the runtime settings state file."""
        return self._settings_path

    def get_state(self) -> SettingsState:
        """Return current mutable settings."""
        return self._state

    def patch(self, updates: SettingsPatch) -> SettingsState:
        """Apply validated updates and schedule persistence."""
        applied = False

        if updates.tts is not None and updates.tts.enabled is not None:
            val = updates.tts.enabled
            self._state.tts.enabled = val
            self._tts_manager.enabled = val
            logger.info("Runtime tts.enabled -> %s", val)
            applied = True

        if not applied:
            raise ValueError("No mutable settings in patch")

        self._schedule_flush()
        return self.get_state()

    @staticmethod
    def parse_patch(raw: object) -> SettingsPatch:
        """Parse a raw JSON body into a typed SettingsPatch."""
        if not isinstance(raw, dict):
            raise ValueError("Expected JSON object")

        allowed_top = {"tts"}
        unknown_top = set(raw) - allowed_top
        if unknown_top:
            raise ValueError(f"Unknown settings keys: {sorted(unknown_top)}")

        tts_patch: TTSSettingsPatch | None = None
        tts_raw = raw.get("tts")
        if tts_raw is not None:
            if not isinstance(tts_raw, dict):
                raise ValueError("tts must be an object")
            allowed_tts = {"enabled"}
            unknown_tts = set(tts_raw) - allowed_tts
            if unknown_tts:
                raise ValueError(f"Unknown tts keys: {sorted(unknown_tts)}")
            enabled_val: bool | None
            if "enabled" in tts_raw:
                raw_enabled = tts_raw["enabled"]
                if not isinstance(raw_enabled, bool):
                    raise ValueError("tts.enabled must be a boolean")
                enabled_val = raw_enabled
            else:
                enabled_val = None
            tts_patch = TTSSettingsPatch(enabled=enabled_val)

        return SettingsPatch(tts=tts_patch)

    def _load_from_disk(self) -> None:
        data = self._read_settings_file()
        if data is None:
            return

        tts_raw = data.get("tts")
        if isinstance(tts_raw, dict):
            enabled_raw = tts_raw.get("enabled")
            if isinstance(enabled_raw, bool):
                self._state.tts.enabled = enabled_raw
                self._tts_manager.enabled = enabled_raw

    def _read_settings_file(self) -> dict[str, object] | None:
        try:
            if not self._settings_path.exists():
                return None
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            logger.exception("Failed to read runtime settings from %s", self._settings_path)
        return None

    def _schedule_flush(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = loop.create_task(self._debounced_flush(), name="settings-debounced-flush")

    async def _debounced_flush(self) -> None:
        await asyncio.sleep(FLUSH_DELAY_S)
        await self._flush_to_disk()

    async def _flush_to_disk(self) -> None:
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "tts": {"enabled": self._state.tts.enabled},
            }
            self._settings_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
            logger.info("Runtime settings flushed to %s", self._settings_path)
        except Exception:
            logger.exception("Failed to flush runtime settings to disk")

"""Mutable runtime settings with debounced YAML persistence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML

if TYPE_CHECKING:
    from teleclaude.chiptunes.manager import ChiptunesManager
    from teleclaude.tts.manager import TTSManager

logger = get_logger(__name__)

FLUSH_DELAY_S = 0.5


@dataclass
class TTSSettings:
    """TTS section of mutable settings."""

    enabled: bool = False


@dataclass
class ChiptunesSettings:
    """ChipTunes section of mutable settings."""

    enabled: bool = False


@dataclass
class SettingsState:
    """Full mutable settings state."""

    tts: TTSSettings
    chiptunes: ChiptunesSettings = field(default_factory=ChiptunesSettings)


@dataclass
class TTSSettingsPatch:
    """Patch payload for TTS settings. All fields optional."""

    enabled: bool | None = None


@dataclass
class ChiptunesSettingsPatch:
    """Patch payload for chiptunes settings. All fields optional."""

    enabled: bool | None = None


@dataclass
class SettingsPatch:
    """Typed patch payload for settings updates."""

    tts: TTSSettingsPatch | None = None
    chiptunes: ChiptunesSettingsPatch | None = None


class RuntimeSettings:
    """In-memory mutable settings layer with debounced persistence to config.yml."""

    def __init__(
        self,
        config_path: Path,
        tts_manager: "TTSManager",
        chiptunes_manager: "ChiptunesManager | None" = None,
    ) -> None:
        self._config_path = config_path
        self._tts_manager = tts_manager
        self._chiptunes_manager = chiptunes_manager
        self._tts_enabled: bool = tts_manager.enabled
        self._chiptunes_enabled: bool = chiptunes_manager.enabled if chiptunes_manager is not None else False
        self._flush_task: asyncio.Task[None] | None = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    def get_state(self) -> SettingsState:
        """Return current mutable settings."""
        return SettingsState(
            tts=TTSSettings(enabled=self._tts_enabled),
            chiptunes=ChiptunesSettings(enabled=self._chiptunes_enabled),
        )

    def patch(self, updates: SettingsPatch) -> SettingsState:
        """Apply validated updates and schedule persistence.

        Returns:
            The full settings state after patching.

        Raises:
            ValueError: If patch contains no recognized fields.
        """
        applied = False

        if updates.tts is not None and updates.tts.enabled is not None:
            val = updates.tts.enabled
            self._tts_enabled = val
            self._tts_manager.enabled = val
            logger.info("Runtime tts.enabled → %s", val)
            applied = True

        if updates.chiptunes is not None and updates.chiptunes.enabled is not None:
            val = updates.chiptunes.enabled
            self._chiptunes_enabled = val
            if self._chiptunes_manager is not None:
                if val:
                    self._chiptunes_manager.start()
                else:
                    self._chiptunes_manager.stop()
            logger.info("Runtime chiptunes.enabled → %s", val)
            applied = True

        if not applied:
            raise ValueError("No mutable settings in patch")

        self._schedule_flush()
        return self.get_state()

    @staticmethod
    def parse_patch(raw: object) -> SettingsPatch:
        """Parse a raw JSON body into a typed SettingsPatch.

        Raises:
            ValueError: If the payload structure is invalid or contains unknown keys.
        """
        if not isinstance(raw, dict):
            raise ValueError("Expected JSON object")

        allowed_top = {"tts", "chiptunes"}
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
            tts_patch = TTSSettingsPatch(
                enabled=enabled_val,
            )

        chiptunes_patch: ChiptunesSettingsPatch | None = None
        chiptunes_raw = raw.get("chiptunes")
        if chiptunes_raw is not None:
            if not isinstance(chiptunes_raw, dict):
                raise ValueError("chiptunes must be an object")
            allowed_chiptunes = {"enabled"}
            unknown_chiptunes = set(chiptunes_raw) - allowed_chiptunes
            if unknown_chiptunes:
                raise ValueError(f"Unknown chiptunes keys: {sorted(unknown_chiptunes)}")
            chiptunes_enabled_val: bool | None = None
            if "enabled" in chiptunes_raw:
                raw_chiptunes_enabled = chiptunes_raw["enabled"]
                if not isinstance(raw_chiptunes_enabled, bool):
                    raise ValueError("chiptunes.enabled must be a boolean")
                chiptunes_enabled_val = raw_chiptunes_enabled
            chiptunes_patch = ChiptunesSettingsPatch(enabled=chiptunes_enabled_val)

        return SettingsPatch(tts=tts_patch, chiptunes=chiptunes_patch)

    def _schedule_flush(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No running event loop — skip deferred flush (sync context)
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = loop.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        await asyncio.sleep(FLUSH_DELAY_S)
        await self._flush_to_disk()

    async def _flush_to_disk(self) -> None:
        """Round-trip config.yml preserving comments and formatting."""
        try:
            doc = self._yaml.load(self._config_path)
            if doc is None:
                doc = {}

            tts_section = doc.get("tts")
            if isinstance(tts_section, dict):
                tts_section["enabled"] = self._tts_enabled
            else:
                doc["tts"] = {"enabled": self._tts_enabled}

            chiptunes_section = doc.get("chiptunes")
            if isinstance(chiptunes_section, dict):
                chiptunes_section["enabled"] = self._chiptunes_enabled
            else:
                doc["chiptunes"] = {"enabled": self._chiptunes_enabled}

            self._yaml.dump(doc, self._config_path)
            logger.info("Settings flushed to %s", self._config_path)
        except Exception:
            logger.exception("Failed to flush settings to disk")

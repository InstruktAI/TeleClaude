"""Mutable runtime settings with debounced YAML persistence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML

from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.tts.manager import TTSManager

logger = get_logger(__name__)

FLUSH_DELAY_S = 0.5
_VALID_PANE_THEMING_MODES = {"full", "semi", "off"}


@dataclass
class TTSSettings:
    """TTS section of mutable settings."""

    enabled: bool = False


@dataclass
class SettingsState:
    """Full mutable settings state."""

    tts: TTSSettings
    pane_theming_mode: str = "full"


@dataclass
class TTSSettingsPatch:
    """Patch payload for TTS settings. All fields optional."""

    enabled: bool | None = None


@dataclass
class SettingsPatch:
    """Typed patch payload for settings updates."""

    tts: TTSSettingsPatch | None = None
    pane_theming_mode: str | None = None


class RuntimeSettings:
    """In-memory mutable settings layer with debounced persistence to config.yml."""

    def __init__(self, config_path: Path, tts_manager: "TTSManager") -> None:
        self._config_path = config_path
        self._tts_manager = tts_manager
        self._tts_enabled: bool = tts_manager.enabled
        self._pane_theming_mode: str = self._normalize_pane_theming_mode(str(config.ui.pane_theming_mode))
        self._flush_task: asyncio.Task[None] | None = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    def get_state(self) -> SettingsState:
        """Return current mutable settings."""
        return SettingsState(
            tts=TTSSettings(enabled=self._tts_enabled),
            pane_theming_mode=self._pane_theming_mode,
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

        if updates.pane_theming_mode is not None:
            self._pane_theming_mode = self._normalize_pane_theming_mode(updates.pane_theming_mode)
            logger.info("Runtime pane_theming_mode → %s", self._pane_theming_mode)
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

        allowed_top = {"tts", "pane_theming_mode"}
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

        pane_theming_mode: str | None = None
        pane_raw = raw.get("pane_theming_mode")
        if pane_raw is not None:
            if not isinstance(pane_raw, str):
                raise ValueError("pane_theming_mode must be a string")
            pane_theming_mode = pane_raw
            # validate here to return consistent parse errors
            _ = RuntimeSettings._normalize_pane_theming_mode(pane_theming_mode)

        return SettingsPatch(tts=tts_patch, pane_theming_mode=pane_theming_mode)

    def _schedule_flush(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.ensure_future(self._debounced_flush())

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

            ui_section = doc.get("ui")
            if isinstance(ui_section, dict):
                ui_section["pane_theming_mode"] = self._pane_theming_mode
            else:
                doc["ui"] = {"pane_theming_mode": self._pane_theming_mode}

            self._yaml.dump(doc, self._config_path)
            logger.info("Settings flushed to %s", self._config_path)
        except Exception:
            logger.exception("Failed to flush settings to disk")

    @staticmethod
    def _normalize_pane_theming_mode(raw: str) -> str:
        """Normalize and validate pane-theming mode values."""
        normalized = raw.strip().lower()
        if normalized not in _VALID_PANE_THEMING_MODES:
            raise ValueError(f"pane_theming_mode must be one of: {', '.join(sorted(_VALID_PANE_THEMING_MODES))}")
        return normalized

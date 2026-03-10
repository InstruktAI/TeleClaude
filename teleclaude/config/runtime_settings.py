"""Mutable runtime settings with debounced JSON persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.chiptunes.manager import ChiptunesManager
    from teleclaude.tts.manager import TTSManager

logger = get_logger(__name__)

FLUSH_DELAY_S = 0.5
PlaybackState = Literal["cold", "playing", "paused"]


@dataclass
class TTSSettings:
    """TTS section of mutable settings."""

    enabled: bool = False


@dataclass
class ChiptunesRuntimeState:
    """Persisted chiptunes runtime state."""

    playback: PlaybackState = "cold"
    track_path: str = ""
    position_seconds: float = 0.0
    history: list[str] = field(default_factory=list)
    history_index: int = -1


@dataclass
class SettingsState:
    """Full mutable runtime state."""

    tts: TTSSettings
    chiptunes: ChiptunesRuntimeState = field(default_factory=ChiptunesRuntimeState)
    chiptunes_state_version: int = 0


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
        tts_manager: "TTSManager",
        chiptunes_manager: "ChiptunesManager | None" = None,
    ) -> None:
        self._settings_path = settings_path
        self._tts_manager = tts_manager
        self._chiptunes_manager = chiptunes_manager
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

    @property
    def chiptunes_state_version(self) -> int:
        """Monotonic version for chiptunes runtime state updates."""
        return self._state.chiptunes_state_version

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

    def bootstrap_chiptunes(self) -> None:
        """Apply persisted chiptunes state to manager on daemon startup."""
        manager = self._chiptunes_manager
        if manager is None:
            return
        manager.restore_runtime_state(self._state.chiptunes)
        if self._state.chiptunes.playback == "playing":
            manager.start_from_runtime_state(self._state.chiptunes)

    def set_chiptunes_paused(self, paused: bool) -> SettingsState:
        """Pause/resume chiptunes while preserving track position and state."""
        manager = self._chiptunes_manager
        if manager is None:
            return self.get_state()

        if paused:
            if manager.is_playing:
                self._tts_manager.on_chiptunes_user_pause()
                manager.pause()
            self._state.chiptunes = manager.capture_runtime_state()
            self._state.chiptunes.playback = "paused"
        else:
            # Resume from memory when loaded, otherwise cold-start from persisted state.
            if manager.enabled:
                manager.resume()
            else:
                resume_state = self._state.chiptunes
                if not resume_state.track_path:
                    manager.start(paused=False)
                else:
                    manager.start_from_runtime_state(resume_state)
            self._state.chiptunes = manager.capture_runtime_state()
            self._state.chiptunes.playback = "playing"

        logger.info("Runtime chiptunes.playback -> %s", self._state.chiptunes.playback)
        self._state.chiptunes_state_version += 1
        self._schedule_flush()
        return self.get_state()

    def sync_chiptunes_state(self) -> None:
        """Mirror manager runtime state into persisted in-memory state."""
        manager = self._chiptunes_manager
        if manager is None:
            return
        self._state.chiptunes = manager.capture_runtime_state()
        self._state.chiptunes_state_version += 1
        self._schedule_flush()

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

        chiptunes_raw = data.get("chiptunes")
        if isinstance(chiptunes_raw, dict):
            playback = chiptunes_raw.get("playback")
            if playback in {"cold", "playing", "paused"}:
                self._state.chiptunes.playback = playback
            track_path = chiptunes_raw.get("track_path")
            if isinstance(track_path, str):
                self._state.chiptunes.track_path = track_path
            position = chiptunes_raw.get("position_seconds")
            if isinstance(position, (int, float)):
                self._state.chiptunes.position_seconds = max(0.0, float(position))
            history = chiptunes_raw.get("history")
            if isinstance(history, list):
                self._state.chiptunes.history = [item for item in history if isinstance(item, str)]
            history_index = chiptunes_raw.get("history_index")
            if isinstance(history_index, int):
                self._state.chiptunes.history_index = history_index
            state_version = chiptunes_raw.get("state_version")
            if isinstance(state_version, int):
                self._state.chiptunes_state_version = max(0, state_version)

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
        self._flush_task = loop.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        await asyncio.sleep(FLUSH_DELAY_S)
        await self._flush_to_disk()

    async def _flush_to_disk(self) -> None:
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "tts": {"enabled": self._state.tts.enabled},
                "chiptunes": {
                    "state_version": self._state.chiptunes_state_version,
                    "playback": self._state.chiptunes.playback,
                    "track_path": self._state.chiptunes.track_path,
                    "position_seconds": self._state.chiptunes.position_seconds,
                    "history": self._state.chiptunes.history,
                    "history_index": self._state.chiptunes.history_index,
                },
            }
            self._settings_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
            logger.info("Runtime settings flushed to %s", self._settings_path)
        except Exception:
            logger.exception("Failed to flush runtime settings to disk")

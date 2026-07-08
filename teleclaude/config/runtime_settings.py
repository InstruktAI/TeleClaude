"""Mutable runtime settings with debounced JSON persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.tts.provision import (
    deprovision_tts_deps_async,
    ensure_tts_provisioned_async,
    supported_services,
    tts_deps_present,
)

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

    async def apply_patch_async(self, updates: SettingsPatch) -> SettingsState:
        """Apply a patch, gating a genuine TTS enable transition on provisioning.

        A False->True ``tts.enabled`` transition first awaits dependency
        provisioning off the event loop; only on success does the flag flip. Any
        ``TTSProvisionError`` propagates with no state mutation (fail closed). A
        mute (True->False) or a no-op delegates straight to the sync patch with no
        provisioning call.
        """
        if self._is_tts_enable_transition(updates):
            await ensure_tts_provisioned_async(config.tts)
        return self.patch(updates)

    def _is_tts_enable_transition(self, updates: SettingsPatch) -> bool:
        """True only for a genuine False->True tts.enabled change."""
        return updates.tts is not None and updates.tts.enabled is True and self._state.tts.enabled is False

    async def deprovision_tts_async(self) -> SettingsState:
        """Force TTS off, persist that durably, then remove the TTS-exclusive deps.

        Distinct from ``patch()``: the off state is written synchronously (not
        debounced) before dependency removal starts, so a persist failure blocks
        removal and never leaves an enabled-but-unprovisioned live state. Never
        routes through the mute path — muting alone must never deprovision.
        """
        self._state.tts.enabled = False
        self._tts_manager.enabled = False
        self._write_state_to_disk()
        await deprovision_tts_deps_async()
        return self.get_state()

    def reconcile_tts_provisioning(self) -> None:
        """Force TTS off at boot when a replayed enabled=True is not ready on this host.

        Runs no install: a persisted/seeded ``enabled=True`` is forced off (state and
        manager) and persisted synchronously when the host supports no enabled service
        or the extra-backed deps are not importable, so the settings API never reports
        ``enabled=True`` on an unprovisioned host.
        """
        if not self._tts_manager.enabled:
            return
        is_supported = bool(supported_services(config.tts))
        deps_present = tts_deps_present(config.tts)
        if is_supported and deps_present:
            return
        logger.warning(
            "tts_boot_reconcile_forced_off",
            supported=is_supported,
            deps_present=deps_present,
        )
        self._state.tts.enabled = False
        self._tts_manager.enabled = False
        self._write_state_to_disk()

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
        # Best-effort: a debounced background flush must never crash the loop.
        try:
            self._write_state_to_disk()
        except OSError:
            logger.exception("Failed to flush runtime settings to disk")

    def _write_state_to_disk(self) -> None:
        """Write current state to disk, propagating any write failure to the caller."""
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tts": {"enabled": self._state.tts.enabled},
        }
        self._settings_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
        logger.info("Runtime settings flushed to %s", self._settings_path)

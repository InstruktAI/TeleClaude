"""Mutable runtime settings with debounced YAML persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML

if TYPE_CHECKING:
    from teleclaude.tts.manager import TTSManager

logger = get_logger(__name__)

MUTABLE_SETTINGS = {"tts.enabled"}
FLUSH_DELAY_S = 0.5


class RuntimeSettings:
    """In-memory mutable settings layer with debounced persistence to config.yml."""

    def __init__(self, config_path: Path, tts_manager: "TTSManager") -> None:
        self._config_path = config_path
        self._tts_manager = tts_manager
        self._tts_enabled: bool = tts_manager.enabled
        self._flush_task: asyncio.Task[None] | None = None
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    def get_state(self) -> dict[str, Any]:  # guard: loose-dict - settings shape varies by key set
        """Return current mutable settings as a nested dict."""
        return {"tts": {"enabled": self._tts_enabled}}

    def patch(self, updates: dict[str, Any]) -> dict[str, Any]:  # guard: loose-dict - caller-provided patch
        """Apply validated updates and schedule persistence.

        Args:
            updates: Nested dict, e.g. {"tts": {"enabled": False}}.

        Returns:
            The full settings state after patching.

        Raises:
            ValueError: If any key is not in the mutable whitelist.
        """
        flat = _flatten(updates)
        invalid = set(flat) - MUTABLE_SETTINGS
        if invalid:
            raise ValueError(f"Immutable or unknown keys: {sorted(invalid)}")

        if "tts.enabled" in flat:
            val = bool(flat["tts.enabled"])
            self._tts_enabled = val
            self._tts_manager.enabled = val
            logger.info("Runtime tts.enabled → %s", val)

        self._schedule_flush()
        return self.get_state()

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

            # Deep-set mutable values
            tts_section = doc.get("tts")
            if isinstance(tts_section, dict):
                tts_section["enabled"] = self._tts_enabled
            else:
                doc["tts"] = {"enabled": self._tts_enabled}

            self._yaml.dump(doc, self._config_path)
            logger.info("Settings flushed to %s", self._config_path)
        except Exception:
            logger.exception("Failed to flush settings to disk")


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:  # guard: loose-dict - recursive flattening
    """Flatten nested dict to dot-notation keys."""
    out: dict[str, Any] = {}  # guard: loose-dict - accumulator for flattened keys
    for k, v in d.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out

"""Daemon-owned watcher over the runtime config files.

A single watcher over a fixed scope (``config.yml`` + ``.env``). It only *detects*
changes (debounced mtime poll, matching the daemon's other periodic tasks) and hands
off to an injected handler, which owns the hot-reload-vs-restart decision.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_POLL_INTERVAL_S = 2.0
_INITIAL_SNAPSHOT_FAILED = "config_watcher_initial_snapshot_failed"
_PATH_RESOLUTION_FAILED = "config_watcher_path_resolution_failed"
_POLL_FAILED = "config_watcher_poll_failed"
_STAT_FAILED = "Config watcher could not stat a watched path: %s"
_STARTED = "Config watcher started (paths=%d, interval=%.0fs)"


class ConfigWatcher:
    """Polls config-file mtimes and invokes a handler once per detected change."""

    def __init__(
        self,
        paths: list[Path] | Callable[[], list[Path]],
        on_change: Callable[[], Awaitable[None]],
        *,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._paths = paths if callable(paths) else lambda: paths
        self._on_change = on_change
        self._poll_interval_s = poll_interval_s
        try:
            self._mtimes = self._snapshot()
        except Exception as exc:
            # Path discovery can fail on a path that names a person, so only the error kind is logged.
            logger.error(_INITIAL_SNAPSHOT_FAILED, error_kind=type(exc).__name__)
            self._mtimes = {}

    def _snapshot(self) -> dict[Path, float | None]:
        snapshot: dict[Path, float | None] = {}
        for path in self._paths():
            try:
                snapshot[path] = path.stat().st_mtime
            except FileNotFoundError:
                snapshot[path] = None
            except OSError as exc:
                # The path and the error text can name a person (home directories), so only the error kind is logged.
                logger.error(_STAT_FAILED, type(exc).__name__)
                snapshot[path] = None
        return snapshot

    def _changed(self) -> bool:
        current = self._snapshot()
        if current != self._mtimes:
            self._mtimes = current
            return True
        return False

    async def run(self) -> None:
        """Poll until cancelled; invoke the handler once per detected change.

        The poll interval is the debounce window: edits that settle within one interval
        coalesce into a single handler invocation, so multi-field TUI saves do not thrash.
        """
        try:
            watched_paths = self._paths()
        except Exception as exc:
            logger.error(_PATH_RESOLUTION_FAILED, error_kind=type(exc).__name__)
            watched_paths = []
        # The paths can name people (home directories), so only their number is logged.
        logger.info(_STARTED, len(watched_paths), self._poll_interval_s)
        try:
            while True:
                await asyncio.sleep(self._poll_interval_s)
                try:
                    if not self._changed():
                        continue
                except Exception as exc:
                    logger.error(_POLL_FAILED, error_kind=type(exc).__name__)
                    continue
                try:
                    await self._on_change()
                except Exception:
                    logger.exception("Config-change handler failed; continuing to watch")
        except asyncio.CancelledError:
            logger.info("Config watcher stopped")
            raise

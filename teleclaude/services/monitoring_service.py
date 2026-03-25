"""Resource and launchd monitoring service."""

from __future__ import annotations

import asyncio
import os
import platform
import resource
import subprocess
import threading
import time
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.api_server import APIServer
from teleclaude.core.lifecycle import DaemonLifecycle
from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

# Resource pressure thresholds
_FD_WARN = 200
_ASYNCIO_TASKS_WARN = 500
_LOOP_LAG_WARN_MS = 1000.0


def _get_fd_count() -> int | None:
    """Return open file descriptor count if available."""
    try:
        return len(os.listdir("/dev/fd"))
    except OSError:
        return None


def _get_rss_kb() -> int | None:
    """Return resident set size in KB when available."""
    try:
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ValueError, OSError):
        return None

    if platform.system().lower() == "darwin":
        return int(rss / 1024)
    return rss


def _log_unnamed_task_diagnostics(unnamed_coros: list[str]) -> None:
    """Log diagnostic info for unnamed asyncio tasks."""
    coro_counts: dict[str, int] = {}
    for entry in unnamed_coros:
        key = entry.split(":", 1)[1] if ":" in entry else entry
        coro_counts[key] = coro_counts.get(key, 0) + 1
    logger.warning(
        "Unnamed task coroutines: %s",
        ", ".join(f"{n}={c}" for n, c in sorted(coro_counts.items(), key=lambda x: -x[1])[:10]),
    )
    stacks: dict[str, int] = {}
    for t in asyncio.all_tasks():
        if not t.get_name().startswith("Task-"):
            continue
        coro = t.get_coro()
        if coro and "Event.wait" in getattr(coro, "__qualname__", ""):
            s = " -> ".join(
                f"{f.f_code.co_filename.split('/')[-1]}:{f.f_lineno}:{f.f_code.co_name}" for f in t.get_stack(limit=6)
            )
            stacks[s] = stacks.get(s, 0) + 1
    for stack, count in sorted(stacks.items(), key=lambda x: -x[1])[:5]:
        logger.warning("Event.wait stack (x%d): %s", count, stack)


class MonitoringService:  # pylint: disable=too-many-instance-attributes
    """Emit resource snapshots and launchd state."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        lifecycle: DaemonLifecycle,
        task_registry: TaskRegistry,
        shutdown_event: asyncio.Event,
        start_time: float,
        resource_snapshot_interval_s: float,
        launchd_watch_interval_s: float,
        db_path: str = "",
    ) -> None:
        self._lifecycle = lifecycle
        self._task_registry = task_registry
        self._shutdown_event = shutdown_event
        self._start_time = start_time
        self._resource_snapshot_interval_s = resource_snapshot_interval_s
        self._launchd_watch_interval_s = launchd_watch_interval_s
        self._db_path = db_path
        self._last_resource_snapshot_time: float | None = None
        self._last_loop_lag_ms: float | None = None
        self._task_hwm: int = 0

    def log_resource_snapshot(self, reason: str) -> None:
        """Collect and log a resource snapshot."""
        snapshot = self._collect_resource_snapshot(reason)
        logger.info("Resource snapshot", **snapshot)
        self._check_pressure(snapshot)

    async def resource_monitor_loop(self) -> None:
        """Periodically log resource snapshots."""
        loop = asyncio.get_running_loop()
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self._resource_snapshot_interval_s)
            if self._shutdown_event.is_set():
                break
            now = loop.time()
            if self._last_resource_snapshot_time is None:
                self._last_loop_lag_ms = 0.0
            else:
                lag_s = (now - self._last_resource_snapshot_time) - self._resource_snapshot_interval_s
                self._last_loop_lag_ms = max(0.0, lag_s * 1000.0)
            self._last_resource_snapshot_time = now
            self.log_resource_snapshot("periodic")

    async def launchd_watch_loop(self) -> None:
        """Periodically log launchd state for this job on macOS."""
        if platform.system().lower() != "darwin":
            return
        last_output: str | None = None
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self._launchd_watch_interval_s)
            if self._shutdown_event.is_set():
                break
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["launchctl", "blame", f"gui/{os.getuid()}/ai.instrukt.teleclaude.daemon"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                output = result.stdout.strip() or result.stderr.strip()
                if not output:
                    output = f"launchctl exit={result.returncode}"
                if output != last_output:
                    logger.info(
                        "Launchd state",
                        event="launchd_state",
                        reason=output,
                        exit_code=result.returncode,
                    )
                    last_output = output
            except OSError as exc:
                logger.warning("Launchd probe failed: %s", exc)

    def _get_wal_size_kb(self) -> int | None:
        if not self._db_path:
            return None
        wal = Path(f"{self._db_path}-wal")
        try:
            return int(wal.stat().st_size / 1024) if wal.exists() else 0
        except OSError:
            return None

    def _collect_resource_snapshot(self, reason: str) -> dict[str, int | float | str | None]:
        api_ws_clients: int | None = None
        api_server = self._lifecycle.api_server
        if isinstance(api_server, APIServer):
            api_ws_clients = len(api_server._ws_clients)  # pylint: disable=protected-access

        tracked = self._task_registry.task_count()
        self._task_hwm = max(self._task_hwm, tracked)

        uptime_s = int(time.time() - self._start_time)
        snapshot: dict[str, int | float | str | None] = {
            "event": "resource_snapshot",
            "reason": reason,
            "pid": os.getpid(),
            "uptime_s": uptime_s,
            "fd_count": _get_fd_count(),
            "rss_kb": _get_rss_kb(),
            "threads": threading.active_count(),
            "asyncio_tasks": len(cast(set[asyncio.Task[object]], asyncio.all_tasks())),
            "tracked_tasks": tracked,
            "tracked_tasks_hwm": self._task_hwm,
            "wal_size_kb": self._get_wal_size_kb(),
            "api_ws_clients": api_ws_clients,
        }
        if self._last_loop_lag_ms is not None:
            snapshot["loop_lag_ms"] = self._last_loop_lag_ms
        return snapshot

    def _check_pressure(self, snapshot: dict[str, int | float | str | None]) -> None:
        fd = snapshot.get("fd_count")
        if isinstance(fd, int) and fd > _FD_WARN:
            logger.warning("Resource pressure: fd_count=%d exceeds threshold %d", fd, _FD_WARN)

        tasks = snapshot.get("asyncio_tasks")
        if isinstance(tasks, int) and tasks > _ASYNCIO_TASKS_WARN:
            breakdown = ""
            unnamed_coros: list[str] = []
            try:
                all_tasks = asyncio.all_tasks()
                name_counts: dict[str, int] = {}
                for t in all_tasks:
                    name = t.get_name()
                    name_counts[name] = name_counts.get(name, 0) + 1
                    # Capture coroutine info for unnamed tasks (Task-NNN pattern)
                    if name.startswith("Task-"):
                        coro = t.get_coro()
                        if coro is not None:
                            coro_name = getattr(coro, "__qualname__", getattr(coro, "__name__", repr(coro)))
                            unnamed_coros.append(f"{name}:{coro_name}")
                top_names = sorted(name_counts.items(), key=lambda x: -x[1])[:15]
                breakdown = ", ".join(f"{n}={c}" for n, c in top_names)
            except RuntimeError:
                breakdown = "(no running loop)"
            logger.warning(
                "Resource pressure: asyncio_tasks=%d exceeds threshold %d | top: %s",
                tasks,
                _ASYNCIO_TASKS_WARN,
                breakdown,
            )
            if unnamed_coros:
                _log_unnamed_task_diagnostics(unnamed_coros)

        lag = snapshot.get("loop_lag_ms")
        if isinstance(lag, (int, float)) and lag > _LOOP_LAG_WARN_MS:
            logger.warning("Resource pressure: loop_lag_ms=%.1f exceeds threshold %.0f", lag, _LOOP_LAG_WARN_MS)

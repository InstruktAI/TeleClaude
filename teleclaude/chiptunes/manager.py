"""ChiptunesManager — thin relay between daemon and subprocess worker.

The worker runs as an independent process with its own GIL, communicating
via a Unix domain socket. Music continues playing through daemon restarts.
The manager relays commands and mirrors state; it owns no playback logic.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.chiptunes.provision import ChiptunesProvisionError, provision_hvsc_corpus_async
from teleclaude.chiptunes.types import ChiptunesState, coerce_chiptunes_state
from teleclaude.config._chiptunes import ChiptunesConfig
from teleclaude.config.machine import config
from teleclaude.paths import CHIPTUNES_PID_PATH, CHIPTUNES_SOCKET_PATH, CHIPTUNES_WORKER_LOG_PATH
from teleclaude.services.process_janitor.registry import ProcessSpawnRegistry

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = get_logger(__name__)

CommandAction = Literal["resume", "pause", "next", "prev"]

_WORKER_MODULE = "teleclaude.chiptunes.worker"
_SOCKET_PROBE_TIMEOUT_SECONDS = 1.0
_TERMINATION_POLL_COUNT = 20
_TERMINATION_POLL_INTERVAL_SECONDS = 0.1
_SOCKET_WAIT_POLL_COUNT = 50
_SOCKET_WAIT_POLL_INTERVAL_SECONDS = 0.1
_WORKER_LEASE_TTL_SECONDS = 1800
CHIPTUNES_PROVISION_FAILED_EVENT = "chiptunes_provision_failed"


def _current_chiptunes_config() -> ChiptunesConfig | None:
    return config.chiptunes


def _chiptunes_enabled() -> bool:
    cfg = _current_chiptunes_config()
    return bool(cfg and cfg.enabled)


def _is_worker_cmdline(cmdline: list[str]) -> bool:
    """Return True only for the exact ``python -m teleclaude.chiptunes.worker`` invocation.

    Matching the ``-m <module>`` argument pair — not a substring — keeps an
    unrelated process that merely mentions the module name from being adopted or
    terminated.
    """
    return any(first == "-m" and second == _WORKER_MODULE for first, second in pairwise(cmdline))


class ChiptunesManager:
    """Thin relay between daemon and chiptunes subprocess worker.

    Relays commands to the worker via Unix socket and mirrors state events
    back to the daemon. Owns no playback logic — the worker subprocess is
    the sole authority on playback state.
    """

    def __init__(
        self,
        music_dir: Path,
        volume: float = 1.0,
        *,
        default_music_dir: Path | None = None,
        registry: ProcessSpawnRegistry | None = None,
        worker_lease_ttl_seconds: int = _WORKER_LEASE_TTL_SECONDS,
    ) -> None:
        self._music_dir = music_dir
        self._default_music_dir = default_music_dir or music_dir
        self._volume = volume
        self._registry = registry or ProcessSpawnRegistry()
        self._worker_lease_ttl_seconds = worker_lease_ttl_seconds
        self._enabled = False
        self._provision_task: asyncio.Task[None] | None = None
        # Advances on every teardown so an awaiting reattach can detect one that ran meanwhile.
        self._teardown_generation = 0
        self._sock: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Last state mirror from worker events
        self._last_state: ChiptunesState = {}
        self.on_track_start: Callable[[str, str], None] | None = None
        self.on_state_change: Callable[[ChiptunesState], None] | None = None
        self.on_command_done: Callable[[str], None] | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        """Return True if chiptunes playback is enabled."""
        return self._enabled

    @property
    def is_playing(self) -> bool:
        """Return True if playback state is 'playing'."""
        return bool(self._last_state.get("playback") == "playing")

    @property
    def last_state(self) -> ChiptunesState:
        """Return the last known worker state dict."""
        return self._last_state

    def stop(self) -> None:
        """Stop playback and terminate the worker."""
        self._stop_worker()
        self._registry.clear_chiptunes()

    def shutdown(self) -> None:
        """Disconnect from worker without killing it (daemon restart)."""
        self._disconnect()

    def pause(self) -> None:
        """Pause playback (e.g. while TTS speaks)."""
        self._send_cmd({"cmd": "pause"})

    def resume(self) -> None:
        """Resume playback after a pause."""
        self._send_cmd({"cmd": "resume"})

    def next_track(self) -> None:
        """Skip to the next track."""
        self._send_cmd({"cmd": "next"})

    def prev_track(self) -> None:
        """Go back to the previous track."""
        self._send_cmd({"cmd": "prev"})

    async def reattach(self) -> None:
        """Reconnect to a live worker, or terminate an unreachable orphan.

        The worker is an independent process that keeps playing across daemon
        restarts. After a restart this manager starts empty and disconnected, so
        the UI would show 'nothing playing' and pause/like/next would have no
        effect. When a worker is alive and its control socket is reachable,
        reattach reconnects to it and requests a state snapshot so the mirrored
        state reflects what is actually playing. When a worker is alive but its
        socket is missing or unreachable, the worker is an orphan that can no
        longer be controlled and would otherwise play forever; reattach
        terminates it and clears the stale registry so the mirrored state stays
        truthful.

        Every worker-lifecycle effect runs on the event loop without suspending.
        The registry write is the single suspension point: it waits on a thread so
        the loop keeps advancing the transactions that hold the database write lock.
        """
        pids, reachable = self._classify_worker()
        if reachable:
            generation = self._teardown_generation
            self._enabled = True
            self._connect()
            self._send_cmd({"cmd": "capture_state"})
            if pids:
                pid = pids[0]
                await asyncio.to_thread(
                    self._registry.register_chiptunes_pid, pid, lease_ttl_seconds=self._worker_lease_ttl_seconds
                )
                if self._teardown_generation != generation:
                    # A teardown ran during the write; drop the lease it may have missed.
                    await asyncio.to_thread(self._registry.clear_chiptunes_pid, pid)
            return
        if pids:
            registered_pid = self._registry.registered_chiptunes_pid()
            self._terminate_workers(pids)
            self._clear_registry()
            if registered_pid is not None:
                await asyncio.to_thread(self._registry.clear_chiptunes_pid, registered_pid)

    async def reload(self) -> asyncio.Task[None] | None:
        """Re-read chiptunes config and apply the gate without holding the event loop on the registry."""
        chiptunes_cfg = _current_chiptunes_config()
        self._apply_config(chiptunes_cfg)
        config_gate_enabled = bool(chiptunes_cfg and chiptunes_cfg.enabled)
        if not config_gate_enabled:
            await self._stop_without_blocking_loop()
            return None
        if self._music_dir_populated():
            self._activate()
            return None
        return self._schedule_provision_then_activate()

    def enqueue_command(self, command_id: str, action: CommandAction) -> None:
        """Enqueue a user command for asynchronous execution."""
        self._enabled = True
        if self._sock is None:
            self._ensure_worker()
            self._connect()
        self._send_cmd({"cmd": action, "command_id": command_id})

    # ------------------------------------------------------------------ #
    # Worker lifecycle                                                     #
    # ------------------------------------------------------------------ #

    def _apply_config(self, chiptunes_cfg: ChiptunesConfig | None) -> None:
        self._music_dir = (
            Path(chiptunes_cfg.music_dir)
            if chiptunes_cfg is not None and chiptunes_cfg.music_dir
            else self._default_music_dir
        )
        self._volume = chiptunes_cfg.volume if chiptunes_cfg is not None else 1.0

    def _music_dir_populated(self) -> bool:
        return self._music_dir.is_dir() and any(self._music_dir.iterdir())

    def _activate(self) -> None:
        self._enabled = True
        self._fire_state_change()

    def _schedule_provision_then_activate(self) -> asyncio.Task[None] | None:
        if self._provision_task is not None and not self._provision_task.done():
            return self._provision_task
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("chiptunes_provision_no_running_loop", music_dir=str(self._music_dir))
            return None
        self._provision_task = loop.create_task(
            self._provision_then_activate(self._music_dir),
            name="chiptunes-provision",
        )
        return self._provision_task

    async def _provision_then_activate(self, music_dir: Path) -> None:
        """Provision the corpus, then activate; a failure while chiptunes is still enabled ends the task with it.

        The daemon reads the task's outcome to report chiptunes degraded.
        """
        try:
            await provision_hvsc_corpus_async(music_dir)
        except ChiptunesProvisionError as exc:
            logger.warning(CHIPTUNES_PROVISION_FAILED_EVENT, music_dir=str(music_dir), error=str(exc))
            if _chiptunes_enabled():
                raise
            return
        if not _chiptunes_enabled():
            return
        self._activate()

    def _ensure_worker(self) -> None:
        """Ensure exactly one reachable worker exists, adopting or replacing as needed.

        A worker whose control socket is reachable is adopted as-is — no second
        worker is spawned. A worker that is alive but unreachable (its socket was
        purged out from under it) is an orphan: it is terminated before a single
        replacement is spawned, so a missing or stale pidfile can never leak a
        duplicate worker.
        """
        pids, reachable = self._classify_worker()
        resolution = self._registry.resolve_chiptunes(live_pids=pids, socket_reachable=reachable)
        if resolution.adopted_pid is not None:
            self._registry.register_chiptunes(
                resolution.adopted_pid,
                lease_ttl_seconds=self._worker_lease_ttl_seconds,
            )
            return
        stale_pids = set(pids)
        if resolution.stale_pid is not None:
            stale_pids.add(resolution.stale_pid)
        if stale_pids:
            self._terminate_workers(sorted(stale_pids))
        self._clear_registry()
        self._registry.clear_chiptunes()
        pid = self._spawn_worker()
        if pid is not None:
            self._registry.register_chiptunes(pid, lease_ttl_seconds=self._worker_lease_ttl_seconds)
        self._await_socket()

    # ------------------------------------------------------------------ #
    # Socket IPC                                                           #
    # ------------------------------------------------------------------ #

    def _connect(self) -> None:
        """Connect to the worker's Unix socket."""
        self._disconnect()
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(CHIPTUNES_SOCKET_PATH))
            with self._lock:
                self._sock = sock
            self._reader_thread = threading.Thread(
                target=self._read_events,
                daemon=True,
                name="chiptunes-reader",
            )
            self._reader_thread.start()
            logger.debug("Connected to ChipTunes worker")
        except OSError as exc:
            logger.warning("Failed to connect to ChipTunes worker: %s", exc)

    def _disconnect(self) -> None:
        """Close the socket connection to the worker."""
        with self._lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _send_cmd(self, cmd: Mapping[str, object]) -> None:  # guard: ipc-envelope
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        try:
            payload = json.dumps(cmd) + "\n"
            sock.sendall(payload.encode())
        except (BrokenPipeError, OSError):
            logger.debug("ChipTunes worker connection lost")
            self._disconnect()

    def _read_events(self) -> None:
        """Read JSON events from the worker socket."""
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        buf = b""
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._handle_event(line.decode())
        except OSError:
            pass
        # Detect unexpected disconnect (crash, network break).
        # Graceful shutdown() calls _disconnect() before the reader exits,
        # so _sock is already None — skip cleanup in that case.
        with self._lock:
            was_connected = self._sock is not None
        if was_connected:
            self._disconnect()
            # Preserve track_path for recovery, reset playback to cold
            recovered_state: ChiptunesState = self._last_state.copy()
            recovered_state["playback"] = "cold"
            recovered_state["position_seconds"] = 0.0
            self._last_state = recovered_state
            logger.info("ChipTunes: worker connection lost, playback state reset to cold")
            self._fire_state_change()

    def _handle_event(self, line: str) -> None:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(raw, dict):
            return
        event = raw.get("event")
        if event == "track_start":
            track_label = str(raw.get("track", ""))
            sid_path = str(raw.get("sid_path", ""))
            self._last_state["track_path"] = sid_path
            self._last_state["playback"] = "playing"
            logger.info("ChipTunes: playing %s", track_label)
            if self.on_track_start is not None:
                try:
                    self.on_track_start(track_label, sid_path)
                except Exception:
                    logger.warning("on_track_start callback error", exc_info=True)
            self._fire_state_change()
        elif event == "state_update":
            state = coerce_chiptunes_state(raw.get("state"))
            if state:
                self._last_state = state
            self._fire_state_change()
        elif event == "command_done":
            command_id = str(raw.get("command_id", ""))
            if self.on_command_done is not None:
                try:
                    self.on_command_done(command_id)
                except Exception:
                    logger.warning("on_command_done callback error", exc_info=True)
            self._fire_state_change()

    def _fire_state_change(self) -> None:
        if self.on_state_change is not None:
            try:
                self.on_state_change(self._last_state)
            except Exception:
                logger.warning("on_state_change callback error", exc_info=True)

    # ------------------------------------------------------------------ #
    # Worker process management                                            #
    # ------------------------------------------------------------------ #

    def _classify_worker(self) -> tuple[list[int], bool]:
        """Return live worker PIDs and whether the control socket is reachable.

        The pidfile is a hint, not proof: the process table is the source of
        truth for liveness, and socket reachability distinguishes a worker to
        adopt (reachable) from an orphan to terminate (unreachable).
        """
        pids = self._find_live_workers()
        reachable = bool(pids) and self._worker_socket_reachable()
        return pids, reachable

    @staticmethod
    def _find_live_workers() -> list[int]:
        """Return PIDs of this user's running chiptunes worker processes."""
        own_uid = os.getuid()
        pids: list[int] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                if not _is_worker_cmdline(proc.info["cmdline"] or []):
                    continue
                if proc.uids().real != own_uid:
                    continue
                pids.append(proc.info["pid"])
            except psutil.Error:
                continue
        return pids

    @staticmethod
    def _worker_socket_reachable() -> bool:
        """Return True if the worker's control socket accepts a connection."""
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(_SOCKET_PROBE_TIMEOUT_SECONDS)
        try:
            probe.connect(str(CHIPTUNES_SOCKET_PATH))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def _terminate_workers(self, pids: list[int]) -> None:
        """SIGTERM the given workers and wait a bounded interval for them to exit."""
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        for _ in range(_TERMINATION_POLL_COUNT):
            if not any(self._pid_alive(pid) for pid in pids):
                return
            threading.Event().wait(_TERMINATION_POLL_INTERVAL_SECONDS)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _clear_registry() -> None:
        """Unlink the worker socket and pidfile, ignoring missing entries."""
        for path in (CHIPTUNES_SOCKET_PATH, CHIPTUNES_PID_PATH):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _spawn_worker(self) -> int | None:
        """Launch a fresh worker subprocess."""
        with open(CHIPTUNES_WORKER_LOG_PATH, "a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "teleclaude.chiptunes.worker",
                    "--music-dir",
                    str(self._music_dir),
                    "--volume",
                    str(self._volume),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return proc.pid

    @staticmethod
    def _await_socket() -> None:
        """Wait a bounded interval for the freshly spawned worker to bind its socket."""
        for _ in range(_SOCKET_WAIT_POLL_COUNT):
            if CHIPTUNES_SOCKET_PATH.exists():
                return
            threading.Event().wait(_SOCKET_WAIT_POLL_INTERVAL_SECONDS)
        logger.warning("ChipTunes worker did not start in time")

    def _stop_worker(self) -> None:
        """Run every worker-lifecycle effect of a stop except the registry write."""
        self._teardown_generation += 1
        self._enabled = False
        self._send_cmd({"cmd": "stop"})
        self._disconnect()
        pids = self._find_live_workers()
        if pids:
            self._terminate_workers(pids)
        self._clear_registry()
        self._last_state = {}

    async def _stop_without_blocking_loop(self) -> None:
        """Stop the worker, waiting for the registry write on a thread.

        The registry entry is snapshotted before the teardown and cleared only if it
        still names that worker, so a replacement spawned while the write waits keeps
        its own entry. With no entry there is nothing to clear and no write is made.
        """
        registered_pid = self._registry.registered_chiptunes_pid()
        self._stop_worker()
        if registered_pid is not None:
            await asyncio.to_thread(self._registry.clear_chiptunes_pid, registered_pid)

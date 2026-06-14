"""ChiptunesManager — thin relay between daemon and subprocess worker.

The worker runs as an independent process with its own GIL, communicating
via a Unix domain socket. Music continues playing through daemon restarts.
The manager relays commands and mirrors state; it owns no playback logic.
"""

from __future__ import annotations

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

from teleclaude.chiptunes.types import ChiptunesState, coerce_chiptunes_state
from teleclaude.paths import CHIPTUNES_PID_PATH, CHIPTUNES_SOCKET_PATH, CHIPTUNES_WORKER_LOG_PATH

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

    def __init__(self, music_dir: Path, volume: float = 1.0) -> None:
        self._music_dir = music_dir
        self._volume = volume
        self._enabled = False
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
        self._enabled = False
        self._send_cmd({"cmd": "stop"})
        self._disconnect()
        self._kill_worker()
        self._last_state = {}

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

    def reattach(self) -> None:
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
        """
        pids, reachable = self._classify_worker()
        if reachable:
            self._enabled = True
            self._connect()
            self._send_cmd({"cmd": "capture_state"})
            return
        if pids:
            self._terminate_workers(pids)
            self._clear_registry()

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

    def _ensure_worker(self) -> None:
        """Ensure exactly one reachable worker exists, adopting or replacing as needed.

        A worker whose control socket is reachable is adopted as-is — no second
        worker is spawned. A worker that is alive but unreachable (its socket was
        purged out from under it) is an orphan: it is terminated before a single
        replacement is spawned, so a missing or stale pidfile can never leak a
        duplicate worker.
        """
        pids, reachable = self._classify_worker()
        if reachable:
            return
        if pids:
            self._terminate_workers(pids)
        self._clear_registry()
        self._spawn_worker()
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

    def _spawn_worker(self) -> None:
        """Launch a fresh worker subprocess."""
        with open(CHIPTUNES_WORKER_LOG_PATH, "a", encoding="utf-8") as log_file:
            subprocess.Popen(
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

    @staticmethod
    def _await_socket() -> None:
        """Wait a bounded interval for the freshly spawned worker to bind its socket."""
        for _ in range(_SOCKET_WAIT_POLL_COUNT):
            if CHIPTUNES_SOCKET_PATH.exists():
                return
            threading.Event().wait(_SOCKET_WAIT_POLL_INTERVAL_SECONDS)
        logger.warning("ChipTunes worker did not start in time")

    def _kill_worker(self) -> None:
        """Terminate any live worker process and clear the registry."""
        pids = self._find_live_workers()
        if pids:
            self._terminate_workers(pids)
        self._clear_registry()

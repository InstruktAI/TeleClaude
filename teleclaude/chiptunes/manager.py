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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from instrukt_ai_logging import get_logger

from teleclaude.paths import CHIPTUNES_WORKER_LOG_PATH

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = get_logger(__name__)

CommandAction = Literal["resume", "pause", "next", "prev"]

SOCKET_PATH = "/tmp/teleclaude-chiptunes.sock"
PID_PATH = "/tmp/teleclaude-chiptunes.pid"


class ChiptunesManager:  # pylint: disable=too-many-instance-attributes
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
        self._last_state: dict[str, Any] = {}
        self.on_track_start: Callable[[str, str], None] | None = None
        self.on_state_change: Callable[[dict[str, Any]], None] | None = None
        self.on_command_done: Callable[[str], None] | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        """Return True if chiptunes playback is enabled."""
        return self._enabled

    @property
    def last_state(self) -> dict[str, Any]:
        """Return the last known worker state dict."""
        return self._last_state

    def start(self) -> None:
        """Ensure worker is running and connect (no start command)."""
        self._enabled = True
        threading.Thread(
            target=self._ensure_and_connect,
            daemon=True,
            name="chiptunes-start",
        ).start()

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

    def _ensure_and_connect(self) -> None:
        if not self._enabled:
            return
        self._ensure_worker()
        self._connect()

    def _ensure_worker(self) -> None:
        """Launch the worker subprocess if not already running."""
        if self._worker_alive():
            return
        for path in (SOCKET_PATH, PID_PATH):
            try:
                os.unlink(path)
            except OSError:
                pass
        subprocess.Popen(  # pylint: disable=consider-using-with
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
            stdout=open(  # noqa: SIM115
                CHIPTUNES_WORKER_LOG_PATH, "a", encoding="utf-8"
            ),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for _ in range(50):
            if os.path.exists(SOCKET_PATH):
                return
            threading.Event().wait(0.1)
        logger.warning("ChipTunes worker did not start in time")

    # ------------------------------------------------------------------ #
    # Socket IPC                                                           #
    # ------------------------------------------------------------------ #

    def _connect(self) -> None:
        """Connect to the worker's Unix socket."""
        self._disconnect()
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(SOCKET_PATH)
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
            self._last_state = {
                **self._last_state,
                "playback": "cold",
                "position_seconds": 0.0,
            }
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
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.warning("on_track_start callback error", exc_info=True)
            self._fire_state_change()
        elif event == "state_update":
            state = raw.get("state")
            if isinstance(state, dict):
                self._last_state = state
            self._fire_state_change()
        elif event == "command_done":
            command_id = str(raw.get("command_id", ""))
            if self.on_command_done is not None:
                try:
                    self.on_command_done(command_id)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.warning("on_command_done callback error", exc_info=True)
            self._fire_state_change()

    def _fire_state_change(self) -> None:
        if self.on_state_change is not None:
            try:
                self.on_state_change(self._last_state)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("on_state_change callback error", exc_info=True)

    # ------------------------------------------------------------------ #
    # Worker process management                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _worker_alive() -> bool:
        """Check if the worker process is running."""
        try:
            pid = int(Path(PID_PATH).read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return True
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            return False

    @staticmethod
    def _kill_worker() -> None:
        """Terminate the worker process."""
        try:
            pid = int(Path(PID_PATH).read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            pass

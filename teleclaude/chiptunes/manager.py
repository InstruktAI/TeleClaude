"""ChiptunesManager — manages a subprocess worker for SID playback.

The worker runs as an independent process with its own GIL, communicating
via a Unix domain socket. Music continues playing through daemon restarts.
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
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

SOCKET_PATH = "/tmp/teleclaude-chiptunes.sock"
PID_PATH = "/tmp/teleclaude-chiptunes.pid"

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


class ChiptunesManager:
    """Manages chiptunes playback via a subprocess worker."""

    def __init__(self, music_dir: Path, volume: float = 0.5) -> None:
        self._music_dir = music_dir
        self._volume = volume
        self._enabled = False
        self._sock: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.on_track_start: Callable[[str], None] | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        """Start playback (launches worker if needed, connects, sends start)."""
        self._enabled = True
        threading.Thread(target=self._start_playback, daemon=True, name="chiptunes-start").start()

    def stop(self) -> None:
        """Stop playback and terminate the worker."""
        self._enabled = False
        self._send_cmd({"cmd": "stop"})
        self._disconnect()
        self._kill_worker()

    def pause(self) -> None:
        self._send_cmd({"cmd": "pause"})

    def resume(self) -> None:
        self._send_cmd({"cmd": "resume"})

    @property
    def is_playing(self) -> bool:
        return self._enabled and self._worker_alive()

    def shutdown(self) -> None:
        """Disconnect from worker without killing it (daemon restart)."""
        self._disconnect()

    def _start_playback(self) -> None:
        if not self._enabled:
            return
        self._ensure_worker()
        self._connect()
        self._send_cmd({"cmd": "start"})

    def _ensure_worker(self) -> None:
        """Launch the worker subprocess if not already running."""
        if self._worker_alive():
            return
        # Clean up stale socket/pid
        for path in (SOCKET_PATH, PID_PATH):
            try:
                os.unlink(path)
            except OSError:
                pass
        subprocess.Popen(
            [
                sys.executable, "-m", "teleclaude.chiptunes.worker",
                "--music-dir", str(self._music_dir),
                "--volume", str(self._volume),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach from daemon process group
        )
        # Wait for socket to appear
        for _ in range(50):  # 5 seconds max
            if os.path.exists(SOCKET_PATH):
                return
            threading.Event().wait(0.1)
        logger.warning("ChipTunes worker did not start in time")

    def _connect(self) -> None:
        """Connect to the worker's Unix socket."""
        self._disconnect()
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(SOCKET_PATH)
            with self._lock:
                self._sock = sock
            self._reader_thread = threading.Thread(
                target=self._read_events, daemon=True, name="chiptunes-reader"
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

    def _send_cmd(self, cmd: dict[str, object]) -> None:
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

    def _handle_event(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        event = msg.get("event")
        if event == "track_start":
            track = msg.get("track", "")
            logger.info("ChipTunes: playing %s", track)
            if self.on_track_start is not None:
                try:
                    self.on_track_start(track)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.debug("on_track_start callback error", exc_info=True)
        elif event == "track_end":
            logger.debug("ChipTunes: track ended")

    @staticmethod
    def _worker_alive() -> bool:
        """Check if the worker process is running."""
        try:
            pid = int(Path(PID_PATH).read_text().strip())
            os.kill(pid, 0)  # signal 0 = check existence
            return True
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            return False

    @staticmethod
    def _kill_worker() -> None:
        """Terminate the worker process."""
        try:
            pid = int(Path(PID_PATH).read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            pass

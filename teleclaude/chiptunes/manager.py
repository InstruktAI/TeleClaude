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

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

from teleclaude.config.runtime_settings import ChiptunesRuntimeState, CommandAction

logger = get_logger(__name__)

SOCKET_PATH = "/tmp/teleclaude-chiptunes.sock"
PID_PATH = "/tmp/teleclaude-chiptunes.pid"


class ChiptunesManager:
    """Manages chiptunes playback via a subprocess worker.

    The worker process owns all playback state: player, history, track
    navigation, and audio output. The manager is a thin IPC client that
    relays commands and receives state events over a Unix socket.

    On daemon shutdown, the manager disconnects without killing the worker,
    so music continues playing. On daemon restart, it reconnects and
    resynchronises state.
    """

    def __init__(self, music_dir: Path, volume: float = 0.5) -> None:
        self._music_dir = music_dir
        self._volume = volume
        self._enabled = False
        self._sock: socket.socket | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Cached state from worker events
        self._cached_state = ChiptunesRuntimeState()
        self._state_version = 0
        self.on_track_start: Callable[[str, str], None] | None = None
        self.on_state_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------ #
    # Public API — matches the interface expected by daemon + routes       #
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        """Return True if chiptunes playback is enabled."""
        return self._enabled

    def start(self, *, paused: bool = False) -> None:
        """Start playback (launches worker if needed, connects, sends start)."""
        self._enabled = True
        threading.Thread(
            target=self._start_playback,
            args=(paused,),
            daemon=True,
            name="chiptunes-start",
        ).start()

    def start_from_runtime_state(self, state: ChiptunesRuntimeState) -> None:
        """Start from persisted runtime state (daemon bootstrap)."""
        self._enabled = True
        self._cached_state = state
        threading.Thread(
            target=self._start_from_state,
            args=(state,),
            daemon=True,
            name="chiptunes-restore",
        ).start()

    def restore_runtime_state(self, state: ChiptunesRuntimeState) -> None:
        """Restore non-playing runtime context without starting audio."""
        self._cached_state = state
        self._enabled = False

    def stop(self) -> None:
        """Stop playback and terminate the worker."""
        self._enabled = False
        self._send_cmd({"cmd": "stop"})
        self._disconnect()
        self._kill_worker()
        self._cached_state = ChiptunesRuntimeState()

    def shutdown(self) -> None:
        """Disconnect from worker without killing it (daemon restart).

        Music continues playing in the subprocess. On next daemon start,
        bootstrap_chiptunes() reconnects.
        """
        self._send_cmd({"cmd": "capture_state"})
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
        self._send_cmd({"cmd": action, "command_id": command_id})

    @property
    def is_playing(self) -> bool:
        """Return True if a track is currently playing."""
        return self._cached_state.playback == "playing"

    @property
    def is_paused(self) -> bool:
        """Return True if a track is loaded but currently paused."""
        return self._cached_state.playback == "paused"

    @property
    def current_track(self) -> str:
        """Return the current track label, if any."""
        path = self._cached_state.track_path
        if not path:
            return ""
        return Path(path).stem.replace("_", " ")

    @property
    def current_sid_path(self) -> str:
        """Return the current SID path, if any."""
        return self._cached_state.track_path

    def capture_runtime_state(self) -> ChiptunesRuntimeState:
        """Return the last known worker state for persistence."""
        state = self._cached_state
        if state.playback == "cold":
            self._enabled = False
        else:
            self._enabled = True
        return state

    # ------------------------------------------------------------------ #
    # Worker lifecycle                                                     #
    # ------------------------------------------------------------------ #

    def _start_playback(self, paused: bool = False) -> None:
        if not self._enabled:
            return
        self._ensure_worker()
        self._connect()
        self._send_cmd({"cmd": "start", "paused": paused})

    def _start_from_state(self, state: ChiptunesRuntimeState) -> None:
        if not self._enabled:
            return
        self._ensure_worker()
        self._connect()
        self._send_cmd(
            {
                "cmd": "start_from_state",
                "state": {
                    "playback": state.playback,
                    "track_path": state.track_path,
                    "position_seconds": state.position_seconds,
                    "history": state.history,
                    "history_index": state.history_index,
                },
            }
        )

    def _ensure_worker(self) -> None:
        """Launch the worker subprocess if not already running."""
        if self._worker_alive():
            return
        for path in (SOCKET_PATH, PID_PATH):
            try:
                os.unlink(path)
            except OSError:
                pass
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
            self._cached_state.track_path = sid_path
            self._cached_state.playback = "playing"
            logger.info("ChipTunes: playing %s", track_label)
            if self.on_track_start is not None:
                try:
                    self.on_track_start(track_label, sid_path)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.debug("on_track_start callback error", exc_info=True)
            self._notify_state_change()
        elif event == "state_update":
            self._apply_state_update(raw)
            self._notify_state_change()
        elif event == "command_done":
            command_id = str(raw.get("command_id", ""))
            if command_id == self._cached_state.pending_command_id:
                self._cached_state.pending_command_id = ""
                self._cached_state.pending_action = ""
            self._notify_state_change()

    def _apply_state_update(self, msg: object) -> None:
        """Update cached state from a worker state_update event."""
        if not isinstance(msg, dict):
            return
        state = msg.get("state")
        if not isinstance(state, dict):
            return
        playback = state.get("playback")
        if isinstance(playback, str):
            self._cached_state.playback = playback  # type: ignore[assignment]
        track_path = state.get("track_path")
        if isinstance(track_path, str):
            self._cached_state.track_path = track_path
        position = state.get("position_seconds")
        if isinstance(position, (int, float)):
            self._cached_state.position_seconds = max(0.0, float(position))
        history = state.get("history")
        if isinstance(history, list):
            self._cached_state.history = [str(h) for h in history]
        history_index = state.get("history_index")
        if isinstance(history_index, int):
            self._cached_state.history_index = history_index

    def _notify_state_change(self) -> None:
        if self.on_state_change is not None:
            try:
                self.on_state_change()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("on_state_change callback error", exc_info=True)

    # ------------------------------------------------------------------ #
    # Worker process management                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _worker_alive() -> bool:
        """Check if the worker process is running."""
        try:
            pid = int(Path(PID_PATH).read_text().strip())
            os.kill(pid, 0)
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

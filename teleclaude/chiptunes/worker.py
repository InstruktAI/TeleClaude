"""Chiptunes subprocess worker — runs SID playback in an isolated process.

Communicates via a Unix domain socket at /tmp/teleclaude-chiptunes.sock.
The daemon connects as a client; the worker accepts one connection at a time.
When the daemon restarts, the old connection closes and the new daemon reconnects.
Music continues playing through reconnections.

Commands (JSON lines, daemon→worker):
  {"cmd": "start", "paused": false}
  {"cmd": "start_from_state", "state": {...}}
  {"cmd": "stop"}
  {"cmd": "pause"}
  {"cmd": "resume"}
  {"cmd": "next", "command_id": "..."}
  {"cmd": "prev", "command_id": "..."}
  {"cmd": "capture_state"}

Events (JSON lines, worker→daemon):
  {"event": "track_start", "track": "...", "sid_path": "..."}
  {"event": "state_update", "state": {...}}
  {"event": "command_done", "command_id": "..."}
"""

from __future__ import annotations

import json
import os
import queue
import random
import signal
import socket
import tempfile
import threading
import time
from pathlib import Path

from teleclaude.chiptunes.player import ChiptunesPlayer
from teleclaude.chiptunes.songlengths import load_songlengths, lookup_duration
from teleclaude.paths import CHIPTUNES_STATE_PATH

SOCKET_PATH = "/tmp/teleclaude-chiptunes.sock"
PID_PATH = "/tmp/teleclaude-chiptunes.pid"
_RSID_MAGIC = b"RSID"
STATE_PATH = CHIPTUNES_STATE_PATH
_PERSIST_INTERVAL_SECONDS = 2.0


def _is_rsid(path: Path) -> bool:
    """Return True if path is an RSID file (interrupt-driven, skip in v1)."""
    try:
        with path.open("rb") as f:
            return f.read(4) == _RSID_MAGIC
    except OSError:
        return False


class _WorkerProcess:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Chiptunes playback worker with socket-based command interface.

    Runs as an independent process. Manages track history, player lifecycle,
    and auto-advance. Communicates with the daemon via JSON-lines over a
    Unix socket.
    """

    def __init__(self, music_dir: Path, volume: float) -> None:
        self._music_dir = music_dir
        self._volume = volume
        self._track_list: list[Path] | None = None
        self._player: ChiptunesPlayer | None = None
        self._conn: socket.socket | None = None
        self._conn_lock = threading.Lock()
        self._running = True
        # Track history and navigation
        self._history: list[Path] = []
        self._history_index: int = -1
        self._current_track: Path | None = None
        self._paused_requested: bool = False
        self._paused_position_seconds: float = 0.0
        self._enabled: bool = False
        self._playback_lock = threading.Lock()
        self._playback_gen = 0
        self._lock = threading.RLock()
        self._songlengths: dict[str, list[float]] = {}
        # Command queue for serial processing
        self._command_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._command_worker = threading.Thread(target=self._command_loop, daemon=True, name="chiptunes-commands")
        self._command_worker.start()
        # State persistence
        self._state_dirty = False
        self._last_persist_time: float = 0.0

    # ------------------------------------------------------------------ #
    # Socket server                                                        #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Main loop: accept connections and process commands."""
        Path(PID_PATH).write_text(str(os.getpid()), encoding="utf-8")

        self._songlengths = load_songlengths(self._music_dir / "DOCUMENTS" / "Songlengths.md5")

        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        server.listen(1)
        server.settimeout(1.0)

        def _term_handler(_signum: int, _frame: object) -> None:
            self._request_stop()

        signal.signal(signal.SIGTERM, _term_handler)

        self._self_resume()

        while self._running:
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            with self._conn_lock:
                self._conn = conn

            self._handle_connection(conn)

            with self._conn_lock:
                self._conn = None

        # Cleanup
        if self._player is not None:
            self._player.stop()
        server.close()
        for path in (SOCKET_PATH, PID_PATH):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _request_stop(self) -> None:
        self._running = False

    def _handle_connection(self, conn: socket.socket) -> None:
        """Read commands from a connected daemon until it disconnects."""
        try:
            buf = b""
            while self._running:
                conn.settimeout(1.0)
                try:
                    data = conn.recv(4096)
                except TimeoutError:
                    if self._enabled and self._player is not None and self._player.is_playing:
                        self._state_dirty = True
                    self._flush_dirty_state()
                    continue
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._process_command(line.decode())
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    # ------------------------------------------------------------------ #
    # Command dispatch                                                     #
    # ------------------------------------------------------------------ #

    def _process_command(self, line: str) -> None:  # pylint: disable=too-many-branches
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(raw, dict):
            return

        cmd = raw.get("cmd")
        command_id = str(raw.get("command_id", ""))

        if cmd == "start":
            paused = bool(raw.get("paused", False))
            self._enabled = True
            self._paused_requested = paused
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-start").start()
        elif cmd == "start_from_state":
            self._restore_state(raw.get("state"))
        elif cmd == "stop":
            self._disable()
        elif cmd == "pause":
            if command_id:
                self._command_queue.put((command_id, "pause"))
            else:
                self._do_pause()
        elif cmd == "resume":
            if command_id:
                self._command_queue.put((command_id, "resume"))
            else:
                self._do_resume()
        elif cmd == "next":
            if command_id:
                self._command_queue.put((command_id, "next"))
            else:
                threading.Thread(target=self._play_next, daemon=True, name="chiptunes-next").start()
        elif cmd == "prev":
            if command_id:
                self._command_queue.put((command_id, "prev"))
            else:
                threading.Thread(target=self._play_prev, daemon=True, name="chiptunes-prev").start()
        elif cmd == "capture_state":
            self._emit_state_update()

    # ------------------------------------------------------------------ #
    # Playback control                                                     #
    # ------------------------------------------------------------------ #

    def _disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._playback_gen += 1
            self._paused_requested = False
            if self._player is not None:
                self._player.stop()
                self._player = None
            self._current_track = None
            self._paused_position_seconds = 0.0
        self._persist_state(immediate=True)
        self._emit_state_update()

    def _do_pause(self) -> None:
        with self._lock:
            player = self._player
            if self._paused_requested and (player is None or player.is_paused):
                return
            self._paused_requested = True
            if player is not None:
                self._paused_position_seconds = player.playback_position_seconds
        if player is not None:
            player.pause()
        self._persist_state(immediate=True)
        self._emit_state_update()

    def _do_resume(self) -> None:
        with self._lock:
            self._enabled = True
            self._paused_requested = False
            player = self._player
            current_track = self._current_track
            start_pos = self._paused_position_seconds
        if player is not None:
            player.resume()
            self._persist_state(immediate=True)
            self._emit_state_update()
            return
        if current_track is not None:
            threading.Thread(
                target=self._play_track,
                args=(current_track,),
                kwargs={"start_position_seconds": start_pos},
                daemon=True,
                name="chiptunes-resume",
            ).start()
        else:
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-resume-cold").start()

    def _restore_state(self, state_raw: object) -> None:
        """Restore playback from persisted state sent by daemon."""
        if not isinstance(state_raw, dict):
            return
        self._enabled = True
        with self._lock:
            self._history = [Path(p) for p in state_raw.get("history", []) if p]
            self._history_index = int(state_raw.get("history_index", -1))
            track_path_str = state_raw.get("track_path", "")
            self._current_track = Path(track_path_str) if track_path_str else None
            self._paused_requested = state_raw.get("playback") == "paused"
            self._paused_position_seconds = max(0.0, float(state_raw.get("position_seconds", 0.0)))

        if self._current_track is not None:
            threading.Thread(
                target=self._play_track,
                args=(self._current_track,),
                daemon=True,
                name="chiptunes-restore",
            ).start()
        else:
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-start").start()

    # ------------------------------------------------------------------ #
    # Track navigation with history                                        #
    # ------------------------------------------------------------------ #

    def _play_track(
        self,
        track: Path,
        start_position_seconds: float | None = None,
    ) -> None:
        """Stop current player, emit track_start, and begin playback."""
        with self._playback_lock:
            with self._lock:
                gen = self._playback_gen + 1
                self._playback_gen = gen
                if self._player is not None:
                    self._player.stop()

                player = ChiptunesPlayer(volume=self._volume)
                player.on_track_end = lambda reason=None: self._on_track_end(reason, gen=gen)  # type: ignore[misc]
                self._player = player
                self._current_track = track
                start_paused = self._paused_requested
                start_position = (
                    self._paused_position_seconds if start_position_seconds is None else start_position_seconds
                )

            track_label = track.stem.replace("_", " ")
            self._emit("track_start", track=track_label, sid_path=str(track))

            player.play(
                track,
                start_paused=start_paused,
                start_position_seconds=max(0.0, start_position),
                max_duration=lookup_duration(self._songlengths, track, subtune=0),
            )
            with self._lock:
                paused_requested = self._paused_requested
            if paused_requested and not start_paused:
                player.pause()
            self._persist_state(immediate=True)
            self._emit_state_update()

    def _play_next(self) -> None:
        """Advance to the next track in history or pick a new random one."""
        with self._lock:
            if not self._enabled:
                return
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                track = self._history[self._history_index]
            else:
                candidate = self._pick_random_track()
                if candidate is None:
                    return
                self._history.append(candidate)
                self._history_index = len(self._history) - 1
                track = candidate

        self._play_track(track)

    def _play_prev(self) -> None:
        """Go back to the previous track in history."""
        with self._lock:
            if not self._enabled:
                return
            if self._history_index > 0:
                self._history_index -= 1
                track = self._history[self._history_index]
            else:
                return
        self._play_track(track)

    def _on_track_end(self, reason: str | None = None, *, gen: int = -1) -> None:
        """Called by the player when a track finishes — auto-advance."""
        with self._lock:
            if gen != self._playback_gen:
                return
        if reason is None:
            reason = self._player.track_end_reason if self._player is not None else None
        if reason == "track_completed":
            if self._enabled:
                threading.Thread(target=self._play_next, daemon=True, name="chiptunes-auto-next").start()
            else:
                self._emit_state_update()
        else:
            self._emit_state_update()

    # ------------------------------------------------------------------ #
    # Command queue (receipt-oriented)                                     #
    # ------------------------------------------------------------------ #

    def _command_loop(self) -> None:
        while True:
            try:
                command_id, action = self._command_queue.get(timeout=_PERSIST_INTERVAL_SECONDS)
            except queue.Empty:
                self._flush_dirty_state()
                continue
            try:
                self._run_command(command_id, action)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            finally:
                self._command_queue.task_done()

    def _run_command(self, command_id: str, action: str) -> None:
        if action == "pause":
            self._do_pause()
        elif action == "resume":
            self._do_resume()
        elif action == "next":
            self._play_next()
        elif action == "prev":
            self._play_prev()
        self._emit("command_done", command_id=command_id)

    # ------------------------------------------------------------------ #
    # Track discovery                                                      #
    # ------------------------------------------------------------------ #

    def _pick_random_track(self) -> Path | None:
        if self._track_list is None:
            self._track_list = self._discover_tracks()
        if not self._track_list:
            return None
        return random.choice(self._track_list)

    def _discover_tracks(self) -> list[Path]:
        if not self._music_dir.exists():
            return []
        return [p for p in self._music_dir.rglob("*.sid") if not _is_rsid(p)]

    # ------------------------------------------------------------------ #
    # IPC emit                                                             #
    # ------------------------------------------------------------------ #

    def _emit(self, event: str, **kwargs: object) -> None:
        """Send a JSON event to the connected daemon (if any)."""
        with self._conn_lock:
            conn = self._conn
        if conn is None:
            return
        try:
            payload = json.dumps({"event": event, **kwargs}) + "\n"
            conn.sendall(payload.encode())
        except (BrokenPipeError, OSError):
            pass

    def _emit_state_update(self) -> None:
        """Emit the full playback state to the daemon."""
        self._emit("state_update", state=self._build_state_snapshot())

    # ------------------------------------------------------------------ #
    # State persistence and self-resume                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_state() -> dict[str, object]:
        """Read state JSON file. Returns dict or empty dict on error."""
        try:
            if STATE_PATH.exists():
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))  # type: ignore[return-value]
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _build_state_snapshot(self) -> dict[str, object]:
        """Assemble current state dict under lock."""
        with self._lock:
            player = self._player
            position = self._paused_position_seconds
            if player is not None:
                position = player.playback_position_seconds
            playback: str
            if player is not None and player.is_playing:
                playback = "playing"
            elif self._paused_requested:
                playback = "paused"
            else:
                playback = "cold"
            return {
                "playback": playback,
                "track_path": str(self._current_track) if self._current_track else "",
                "position_seconds": max(0.0, position),
                "history": [str(p) for p in self._history],
                "history_index": self._history_index,
            }

    def _persist_state(self, *, immediate: bool = False) -> None:
        """Write state to disk via tempfile+rename. Debounced unless immediate."""
        now = time.monotonic()
        if not immediate and (now - self._last_persist_time) < _PERSIST_INTERVAL_SECONDS:
            self._state_dirty = True
            return
        snapshot = self._build_state_snapshot()
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(STATE_PATH.parent), suffix=".tmp")
            try:
                os.write(fd, (json.dumps(snapshot) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(tmp, str(STATE_PATH))
        except OSError:
            pass
        self._last_persist_time = now
        self._state_dirty = False

    def _flush_dirty_state(self) -> None:
        """Flush if dirty and interval elapsed."""
        if self._state_dirty and (time.monotonic() - self._last_persist_time) >= _PERSIST_INTERVAL_SECONDS:
            self._persist_state(immediate=True)

    def _self_resume(self) -> None:
        """Resume from state file on startup (before any daemon connects)."""
        state = self._load_state()
        if not state:
            return
        playback = state.get("playback")
        if playback == "playing":
            # Restore history and track, start playing from position 0
            with self._lock:
                self._history = [Path(p) for p in state.get("history", []) if p]  # type: ignore[union-attr]
                self._history_index = int(state.get("history_index", -1))  # type: ignore[arg-type]
                track_path_str = state.get("track_path", "")
                self._current_track = Path(track_path_str) if track_path_str else None  # type: ignore[arg-type]
                self._enabled = True
                self._paused_requested = False
            if self._current_track is not None:
                threading.Thread(
                    target=self._play_track,
                    args=(self._current_track,),
                    kwargs={"start_position_seconds": 0.0},
                    daemon=True,
                    name="chiptunes-self-resume",
                ).start()
            else:
                threading.Thread(target=self._play_next, daemon=True, name="chiptunes-self-resume-next").start()
        elif playback == "paused":
            # Restore context, wait for commands
            with self._lock:
                self._history = [Path(p) for p in state.get("history", []) if p]  # type: ignore[union-attr]
                self._history_index = int(state.get("history_index", -1))  # type: ignore[arg-type]
                track_path_str = state.get("track_path", "")
                self._current_track = Path(track_path_str) if track_path_str else None  # type: ignore[arg-type]
                self._paused_requested = True
                self._paused_position_seconds = max(0.0, float(state.get("position_seconds", 0.0)))  # type: ignore[arg-type]
                self._enabled = True


# ------------------------------------------------------------------ #
# Subprocess entry point                                               #
# ------------------------------------------------------------------ #


def _run() -> None:
    import argparse  # pylint: disable=import-outside-toplevel

    parser = argparse.ArgumentParser()
    parser.add_argument("--music-dir", required=True)
    parser.add_argument("--volume", type=float, default=0.5)
    args = parser.parse_args()

    worker = _WorkerProcess(Path(args.music_dir), args.volume)
    worker.run()


if __name__ == "__main__":
    _run()

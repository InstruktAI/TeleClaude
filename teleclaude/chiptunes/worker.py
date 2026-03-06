"""Chiptunes subprocess worker — runs SID playback in an isolated process.

Communicates via a Unix domain socket at /tmp/teleclaude-chiptunes.sock.
The daemon connects as a client; the worker accepts one connection at a time.
When the daemon restarts, the old connection closes and the new daemon reconnects.
Music continues playing through reconnections.

Commands (JSON lines, daemon→worker):
  {"cmd": "start"}           Start playing a random track
  {"cmd": "stop"}            Stop playback
  {"cmd": "pause"}           Pause audio output
  {"cmd": "resume"}          Resume audio output

Events (JSON lines, worker→daemon):
  {"event": "track_start", "track": "Song Name"}
  {"event": "track_end"}
"""

from __future__ import annotations

import json
import os
import random
import signal
import socket
import threading
from pathlib import Path

from teleclaude.chiptunes.player import ChiptunesPlayer

SOCKET_PATH = "/tmp/teleclaude-chiptunes.sock"
PID_PATH = "/tmp/teleclaude-chiptunes.pid"

_RSID_MAGIC = b"RSID"


def _is_rsid(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == _RSID_MAGIC
    except OSError:
        return False


class _Worker:
    """Chiptunes playback worker with socket-based command interface."""

    def __init__(self, music_dir: Path, volume: float) -> None:
        self._music_dir = music_dir
        self._volume = volume
        self._track_list: list[Path] | None = None
        self._player: ChiptunesPlayer | None = None
        self._conn: socket.socket | None = None
        self._conn_lock = threading.Lock()
        self._running = True

    def run(self) -> None:
        """Main loop: accept connections and process commands."""
        Path(PID_PATH).write_text(str(os.getpid()))

        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        server.listen(1)
        server.settimeout(1.0)

        signal.signal(signal.SIGTERM, lambda *_: self._request_stop())

        while self._running:
            try:
                conn, _ = server.accept()
            except socket.timeout:
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
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break  # daemon disconnected
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

    def _process_command(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        cmd = msg.get("cmd")
        if cmd == "start":
            self._play_random()
        elif cmd == "stop":
            if self._player is not None:
                self._player.stop()
                self._player = None
        elif cmd == "pause":
            if self._player is not None:
                self._player.pause()
        elif cmd == "resume":
            if self._player is not None:
                self._player.resume()

    def _play_random(self) -> None:
        track = self._pick_random_track()
        if track is None:
            return

        if self._player is not None:
            self._player.stop()

        player = ChiptunesPlayer(volume=self._volume)
        player.on_track_end = self._on_track_end
        self._player = player
        track_label = track.stem.replace("_", " ")
        self._emit("track_start", track=track_label)
        player.play(track)

    def _on_track_end(self) -> None:
        """Auto-advance to next track (works even without daemon connection)."""
        self._play_random()

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


def _run() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--music-dir", required=True)
    parser.add_argument("--volume", type=float, default=0.5)
    args = parser.parse_args()

    worker = _Worker(Path(args.music_dir), args.volume)
    worker.run()


if __name__ == "__main__":
    _run()

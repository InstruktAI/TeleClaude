"""Chiptunes playback worker — track history and navigation state."""

from __future__ import annotations

import random
import queue
import threading
from pathlib import Path
from typing import Callable

from instrukt_ai_logging import get_logger

from teleclaude.config.runtime_settings import ChiptunesRuntimeState, CommandAction
from teleclaude.chiptunes.player import ChiptunesPlayer

logger = get_logger(__name__)
_RSID_MAGIC = b"RSID"


def _is_rsid(path: Path) -> bool:
    """Return True if path is an RSID file (interrupt-driven, skip in v1)."""
    try:
        with path.open("rb") as handle:
            return handle.read(4) == _RSID_MAGIC
    except OSError:
        return False


class _Worker:  # pyright: ignore[reportUnusedClass]
    """Manages chiptunes playback with session-scoped track history.

    The worker maintains an ordered history of played tracks so the user can
    navigate backwards. ``_play_next()`` either advances the history index or
    picks a new random track when at the end. ``_play_prev()`` goes back one
    step; at the beginning of history it is a no-op.
    """

    def __init__(
        self,
        pick_random_track: Callable[[], Path | None] | Path,
        volume: float,
        on_track_start: Callable[[str, str], None] | None = None,
        on_state_change: Callable[[], None] | None = None,
    ) -> None:
        self._music_dir: Path | None = None
        if isinstance(pick_random_track, Path):
            self._music_dir = pick_random_track
            self._pick_random_track = self._pick_random_track_from_dir
        else:
            self._pick_random_track = pick_random_track
        self._volume = volume
        self.on_track_start = on_track_start
        self.on_state_change = on_state_change

        self._history: list[Path] = []
        self._history_index: int = -1
        self._player: ChiptunesPlayer | None = None
        self._enabled: bool = False
        self._current_track: Path | None = None
        self._paused_requested: bool = False
        self._paused_position_seconds: float = 0.0
        self._loading: bool = False
        self._pending_command_id: str = ""
        self._pending_action: str = ""
        self._lock = threading.RLock()
        self._command_queue: queue.Queue[tuple[str, CommandAction]] = queue.Queue()
        self._command_worker = threading.Thread(target=self._command_loop, daemon=True, name="chiptunes-commands")
        self._command_worker.start()

    # ------------------------------------------------------------------ #
    # Public control                                                        #
    # ------------------------------------------------------------------ #

    def enable(self, *, start_paused: bool = False) -> None:
        """Mark worker as enabled and start the first track."""
        self._enabled = True
        self._paused_requested = start_paused
        self._loading = True
        self._notify_state_change()
        threading.Thread(target=self._play_next, daemon=True, name="chiptunes-start").start()

    def start_from_state(self, state: ChiptunesRuntimeState) -> None:
        """Start playback from persisted runtime state."""
        with self._lock:
            self._enabled = True
            self._paused_requested = state.playback == "paused"
            self._paused_position_seconds = max(0.0, state.position_seconds)
            self._history = [Path(item) for item in state.history if item]
            self._history_index = state.history_index
            self._current_track = Path(state.track_path) if state.track_path else None
            self._loading = state.playback == "loading" or state.playback == "playing"
            self._pending_command_id = state.pending_command_id
            self._pending_action = state.pending_action
        self._notify_state_change()
        if self._current_track is None:
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-start").start()
            return
        threading.Thread(
            target=self._play_track,
            args=(self._current_track,),
            daemon=True,
            name="chiptunes-resume",
        ).start()

    def disable(self) -> None:
        """Mark worker as disabled and stop playback."""
        with self._lock:
            self._enabled = False
            self._paused_requested = False
            if self._player is not None:
                self._player.stop()
                self._player = None
            self._current_track = None
            self._paused_position_seconds = 0.0
            self._loading = False
            self._pending_command_id = ""
            self._pending_action = ""
        self._notify_state_change()

    def pause(self) -> None:
        """Pause current playback."""
        with self._lock:
            player = self._player
            if self._paused_requested and (player is None or player.is_paused):
                return
            self._paused_requested = True
            if player is not None:
                self._paused_position_seconds = player.playback_position_seconds
        if player is not None:
            player.pause()
        self._notify_state_change()

    def resume(self) -> None:
        """Resume paused playback."""
        with self._lock:
            self._paused_requested = False
            player = self._player
            current_track = self._current_track
            start_pos = self._paused_position_seconds
        if player is not None:
            self._player.resume()
            self._notify_state_change()
            return
        if current_track is not None:
            with self._lock:
                self._loading = True
            self._notify_state_change()
            threading.Thread(
                target=self._play_track,
                args=(current_track,),
                kwargs={"start_position_seconds": start_pos},
                daemon=True,
                name="chiptunes-resume",
            ).start()
        else:
            # Cold resume: start a fresh random track.
            with self._lock:
                self._loading = True
            self._notify_state_change()
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-resume-cold").start()
        self._notify_state_change()

    @property
    def is_playing(self) -> bool:
        """Return True if a track is currently active."""
        return self._player is not None and self._player.is_playing

    @property
    def is_paused(self) -> bool:
        """Return True if a track is loaded but currently paused."""
        if self._player is not None and self._player.is_paused:
            return True
        return self._enabled and self._paused_requested

    @property
    def current_track(self) -> Path | None:
        """Return the currently selected track path, if any."""
        return self._current_track

    @property
    def current_track_label(self) -> str:
        """Return the current track label, if any."""
        if self._current_track is None:
            return ""
        return self._current_track.stem.replace("_", " ")

    @property
    def has_loaded_track(self) -> bool:
        """Return True if playback context is loaded."""
        return self._current_track is not None

    def capture_runtime_state(self) -> ChiptunesRuntimeState:
        """Capture current runtime state for persistence."""
        with self._lock:
            playback: str
            if self._loading:
                playback = "loading"
            elif self._player is not None and self._player.is_playing:
                playback = "playing"
            elif self._paused_requested:
                playback = "paused"
            else:
                playback = "cold"
            position = self._paused_position_seconds
            if self._player is not None:
                position = self._player.playback_position_seconds
            return ChiptunesRuntimeState(
                playback=playback,
                track_path=str(self._current_track) if self._current_track is not None else "",
                position_seconds=max(0.0, position),
                history=[str(item) for item in self._history],
                history_index=self._history_index,
                pending_command_id=self._pending_command_id,
                pending_action=self._pending_action,
            )

    def handle_cmd(self, cmd: dict[str, object]) -> None:  # guard: loose-dict - cmd payload
        """Dispatch a command dict to the appropriate navigation method.

        Supported commands: ``{"cmd": "next"}``, ``{"cmd": "prev"}``.
        """
        name = cmd.get("cmd")
        if name == "next":
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-next").start()
        elif name == "prev":
            threading.Thread(target=self._play_prev, daemon=True, name="chiptunes-prev").start()
        else:
            logger.warning("ChipTunes: unknown command %r", name)

    def enqueue_command(self, command_id: str, action: CommandAction) -> None:
        """Queue command for serial asynchronous processing."""
        with self._lock:
            self._enabled = True
            self._pending_command_id = command_id
            self._pending_action = action
            if action in {"resume", "next", "prev"}:
                self._loading = True
        self._notify_state_change()
        self._command_queue.put((command_id, action))

    # ------------------------------------------------------------------ #
    # Internal navigation                                                   #
    # ------------------------------------------------------------------ #

    def _play_track(self, track: Path, start_position_seconds: float | None = None) -> None:
        """Stop current player, emit track_start callback, and start playback."""
        with self._lock:
            if self._player is not None:
                self._player.stop()

            player = ChiptunesPlayer(volume=self._volume)
            player.on_track_end = self._on_track_end
            self._player = player
            self._current_track = track
            start_paused = self._paused_requested
            start_position = self._paused_position_seconds if start_position_seconds is None else start_position_seconds
            self._loading = True

        track_label = track.stem.replace("_", " ")
        logger.info("ChipTunes: playing %s", track_label)

        if self.on_track_start is not None:
            self.on_track_start(track_label, str(track))

        player.play(track, start_paused=start_paused, start_position_seconds=max(0.0, start_position))
        with self._lock:
            paused_requested = self._paused_requested
            self._loading = False
        if paused_requested and not start_paused:
            player.pause()
        self._finalize_pending_command()
        self._notify_state_change()

    def _play_next(self) -> None:
        """Advance to the next track.

        If the history index is not at the end, advance it and replay from
        history. Otherwise pick a new random track, append it, and play it.
        """
        track: Path | None = None
        need_pick = False
        with self._lock:
            if not self._enabled:
                self._loading = False
                return

            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                track = self._history[self._history_index]
            else:
                need_pick = True

        if need_pick:
            candidate = self._pick_random_track()
            with self._lock:
                if not self._enabled:
                    self._loading = False
                    return
                if self._history_index < len(self._history) - 1:
                    self._history_index += 1
                    track = self._history[self._history_index]
                else:
                    if candidate is None:
                        logger.warning("ChipTunes: no tracks available for next()")
                        self._loading = False
                        return
                    self._history.append(candidate)
                    self._history_index = len(self._history) - 1
                    track = candidate

        if track is not None:
            self._play_track(track)

    def _pick_random_track_from_dir(self) -> Path | None:
        tracks = self._discover_tracks()
        if not tracks:
            return None
        return random.choice(tracks)

    def _play_prev(self) -> None:
        """Go back to the previous track in history.

        No-op when already at the beginning of the history.
        """
        with self._lock:
            if not self._enabled:
                self._loading = False
                return

            if self._history_index > 0:
                self._history_index -= 1
                track = self._history[self._history_index]
            else:
                logger.debug("ChipTunes: already at beginning of history, prev() is a no-op")
                self._loading = False
                self._finalize_pending_command()
                self._notify_state_change()
                return

        self._play_track(track)

    def _on_track_end(self, reason: str | None = None) -> None:
        """Called by the player when a track finishes — auto-advance."""
        if reason is None:
            reason = self._player.track_end_reason if self._player is not None else None
        track_end_reason = reason
        if track_end_reason == "stream_open_failed":
            logger.debug("ChipTunes: track ended due to stream open failure, not auto-advancing")
            self._notify_state_change()
            return
        if self._enabled:
            logger.debug("ChipTunes: track ended, advancing to next")
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-auto-next").start()
        else:
            self._notify_state_change()

    def _command_loop(self) -> None:
        while True:
            command_id, action = self._command_queue.get()
            try:
                self._run_command(action)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("ChipTunes command failed: %s", action)
                with self._lock:
                    if self._pending_command_id == command_id:
                        self._loading = False
                        self._pending_command_id = ""
                        self._pending_action = ""
                self._notify_state_change()
            finally:
                self._command_queue.task_done()

    def _run_command(self, action: CommandAction) -> None:
        if action == "pause":
            self.pause()
            with self._lock:
                self._loading = False
            self._finalize_pending_command()
            self._notify_state_change()
            return
        if action == "resume":
            self.resume()
            # cold->resume completes asynchronously in _play_track
            with self._lock:
                if not self._loading:
                    self._finalize_pending_command()
            self._notify_state_change()
            return
        if action == "next":
            self._play_next()
            with self._lock:
                if not self._loading:
                    self._finalize_pending_command()
            self._notify_state_change()
            return
        if action == "prev":
            self._play_prev()
            with self._lock:
                if not self._loading:
                    self._finalize_pending_command()
            self._notify_state_change()
            return
        logger.warning("ChipTunes: unsupported queued command %s", action)
        with self._lock:
            self._loading = False
            self._finalize_pending_command()
        self._notify_state_change()

    def _finalize_pending_command(self) -> None:
        with self._lock:
            self._pending_command_id = ""
            self._pending_action = ""

    def _discover_tracks(self) -> list[Path]:
        """Collect PSID tracks when worker is initialized with a music directory."""
        if self._music_dir is None:
            return []
        if not self._music_dir.exists():
            logger.warning("ChipTunes music_dir does not exist: %s", self._music_dir)
            return []

        tracks: list[Path] = []
        for sid_path in self._music_dir.rglob("*.sid"):
            if not _is_rsid(sid_path):
                tracks.append(sid_path)
        return tracks

    def _notify_state_change(self) -> None:
        if self.on_state_change is None:
            return
        try:
            self.on_state_change()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("on_state_change callback error", exc_info=True)

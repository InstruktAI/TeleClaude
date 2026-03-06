"""Chiptunes playback worker — track history and navigation state."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from instrukt_ai_logging import get_logger

from teleclaude.chiptunes.player import ChiptunesPlayer

logger = get_logger(__name__)


class _Worker:  # pyright: ignore[reportUnusedClass]
    """Manages chiptunes playback with session-scoped track history.

    The worker maintains an ordered history of played tracks so the user can
    navigate backwards. ``_play_next()`` either advances the history index or
    picks a new random track when at the end. ``_play_prev()`` goes back one
    step; at the beginning of history it is a no-op.
    """

    def __init__(
        self,
        pick_random_track: Callable[[], Path | None],
        volume: float,
        on_track_start: Callable[[str, str], None] | None = None,
    ) -> None:
        self._pick_random_track = pick_random_track
        self._volume = volume
        self.on_track_start = on_track_start

        self._history: list[Path] = []
        self._history_index: int = -1
        self._player: ChiptunesPlayer | None = None
        self._enabled: bool = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Public control                                                        #
    # ------------------------------------------------------------------ #

    def enable(self) -> None:
        """Mark worker as enabled and start the first track."""
        self._enabled = True
        threading.Thread(target=self._play_next, daemon=True, name="chiptunes-start").start()

    def disable(self) -> None:
        """Mark worker as disabled and stop playback."""
        with self._lock:
            self._enabled = False
            if self._player is not None:
                self._player.stop()
                self._player = None

    def pause(self) -> None:
        """Pause current playback."""
        if self._player is not None:
            self._player.pause()

    def resume(self) -> None:
        """Resume paused playback."""
        if self._player is not None:
            self._player.resume()

    @property
    def is_playing(self) -> bool:
        """Return True if a track is currently active."""
        return self._player is not None and self._player.is_playing

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

    # ------------------------------------------------------------------ #
    # Internal navigation                                                   #
    # ------------------------------------------------------------------ #

    def _play_track(self, track: Path) -> None:
        """Stop current player, emit track_start callback, and start playback."""
        with self._lock:
            if self._player is not None:
                self._player.stop()

            player = ChiptunesPlayer(volume=self._volume)
            player.on_track_end = self._on_track_end
            self._player = player

        track_label = track.stem.replace("_", " ")
        logger.info("ChipTunes: playing %s", track_label)

        if self.on_track_start is not None:
            self.on_track_start(track_label, str(track))

        player.play(track)

    def _play_next(self) -> None:
        """Advance to the next track.

        If the history index is not at the end, advance it and replay from
        history. Otherwise pick a new random track, append it, and play it.
        """
        with self._lock:
            if not self._enabled:
                return

            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                track = self._history[self._history_index]
            else:
                track = self._pick_random_track()
                if track is None:
                    logger.warning("ChipTunes: no tracks available for next()")
                    return
                self._history.append(track)
                self._history_index = len(self._history) - 1

        self._play_track(track)

    def _play_prev(self) -> None:
        """Go back to the previous track in history.

        No-op when already at the beginning of the history.
        """
        with self._lock:
            if not self._enabled:
                return

            if self._history_index > 0:
                self._history_index -= 1
                track = self._history[self._history_index]
            else:
                logger.debug("ChipTunes: already at beginning of history, prev() is no-op")
                return

        self._play_track(track)

    def _on_track_end(self) -> None:
        """Called by the player when a track finishes — auto-advance."""
        if self._enabled:
            logger.debug("ChipTunes: track ended, advancing to next")
            threading.Thread(target=self._play_next, daemon=True, name="chiptunes-auto-next").start()

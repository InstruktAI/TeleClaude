"""ChiptunesManager — manages random SID playback lifecycle."""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

from teleclaude.config.runtime_settings import ChiptunesRuntimeState
from teleclaude.chiptunes.worker import _Worker

logger = get_logger(__name__)

_RSID_MAGIC = b"RSID"


def _is_rsid(path: Path) -> bool:
    """Return True if path is an RSID file (interrupt-driven, skip in v1)."""
    try:
        with path.open("rb") as f:
            magic = f.read(4)
        return magic == _RSID_MAGIC
    except OSError:
        return False


class ChiptunesManager:
    """Manages random SID track selection, playback lifecycle, and auto-advance."""

    def __init__(self, music_dir: Path, volume: float = 0.5) -> None:
        self._music_dir = music_dir
        self._volume = volume
        self._track_list: list[Path] | None = None  # lazy-cached on first use
        self._enabled = False
        self.on_track_start: Callable[[str, str], None] | None = None
        self.on_state_change: Callable[[], None] | None = None
        self._worker = _Worker(
            pick_random_track=self._pick_random_track,
            volume=volume,
            on_track_start=self._on_track_start,
            on_state_change=self._on_state_change,
        )

    def _on_track_start(self, track_label: str, sid_path: str) -> None:
        """Forward track_start to the outer callback."""
        if self.on_track_start is not None:
            try:
                self.on_track_start(track_label, sid_path)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("on_track_start callback error", exc_info=True)

    def _on_state_change(self) -> None:
        """Forward chiptunes state changes to the outer callback."""
        if self.on_state_change is not None:
            try:
                self.on_state_change()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("on_state_change callback error", exc_info=True)

    @property
    def enabled(self) -> bool:
        """Return True if chiptunes playback is enabled."""
        return self._enabled

    def start(self, *, paused: bool = False) -> None:
        """Pick a random PSID track and start playback (non-blocking)."""
        self._enabled = True
        self._worker.enable(start_paused=paused)

    def start_from_runtime_state(self, state: ChiptunesRuntimeState) -> None:
        """Start from persisted runtime state."""
        self._enabled = True
        self._worker.start_from_state(state)

    def restore_runtime_state(self, state: ChiptunesRuntimeState) -> None:
        """Restore non-playing runtime context without loading audio engine."""
        self._enabled = False

    def stop(self) -> None:
        """Stop playback immediately."""
        self._enabled = False
        self._worker.disable()

    def pause(self) -> None:
        """Pause playback (e.g. while TTS speaks)."""
        self._worker.pause()

    def resume(self) -> None:
        """Resume playback after a pause."""
        self._worker.resume()

    def next_track(self) -> None:
        """Skip to the next track (advance history or pick new random)."""
        self._worker.handle_cmd({"cmd": "next"})

    def prev_track(self) -> None:
        """Go back to the previous track in session history."""
        self._worker.handle_cmd({"cmd": "prev"})

    @property
    def is_playing(self) -> bool:
        """Return True if a track is currently playing."""
        return self._worker.is_playing

    @property
    def is_paused(self) -> bool:
        """Return True if a track is loaded but currently paused."""
        return self._worker.is_paused

    @property
    def current_track(self) -> str:
        """Return the current track label, if any."""
        return self._worker.current_track_label

    @property
    def current_sid_path(self) -> str:
        """Return the current SID path, if any."""
        track = self._worker.current_track
        return str(track) if track is not None else ""

    def capture_runtime_state(self) -> ChiptunesRuntimeState:
        """Capture full runtime playback state for persistence."""
        state = self._worker.capture_runtime_state()
        if state.playback == "cold":
            self._enabled = False
        else:
            self._enabled = True
        return state

    def _pick_random_track(self) -> Path | None:
        """Lazily discover and cache all PSID tracks, then pick one at random."""
        if self._track_list is None:
            self._track_list = self._discover_tracks()

        if not self._track_list:
            return None

        return random.choice(self._track_list)

    def _discover_tracks(self) -> list[Path]:
        """Walk music_dir and collect all .sid files that are PSID format."""
        if not self._music_dir.exists():
            logger.warning("ChipTunes music_dir does not exist: %s", self._music_dir)
            return []

        tracks: list[Path] = []
        for sid_path in self._music_dir.rglob("*.sid"):
            if not _is_rsid(sid_path):
                tracks.append(sid_path)

        logger.info("ChipTunes: discovered %d PSID tracks in %s", len(tracks), self._music_dir)
        return tracks

"""Audio focus coordination between foreground speech and background music."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.chiptunes.manager import ChiptunesManager

logger = get_logger(__name__)


class AudioFocusCoordinator:
    """Keep background music paused while foreground speech is pending."""

    def __init__(self) -> None:
        self._chiptunes_manager: ChiptunesManager | None = None
        self._foreground_claims = 0
        self._background_paused = False

    @property
    def active_claims(self) -> int:
        """Return the number of queued or active foreground speech claims."""
        return self._foreground_claims

    def set_chiptunes_manager(self, manager: ChiptunesManager | None) -> None:
        """Attach the background music manager."""
        self._chiptunes_manager = manager

    def claim_foreground(self) -> None:
        """Pause background music for a new foreground speech request."""
        self._foreground_claims += 1
        if self._foreground_claims != 1:
            return
        self._pause_background()

    def on_background_state_change(self) -> None:
        """Re-assert foreground ownership when background audio changes state."""
        if self._foreground_claims == 0:
            return
        self._pause_background()

    def release_foreground(self) -> None:
        """Release a foreground speech claim and resume music when drained."""
        if self._foreground_claims == 0:
            return
        self._foreground_claims -= 1
        if self._foreground_claims != 0:
            return
        self._resume_background()

    def reset(self) -> None:
        """Drop all claims and restore background playback state."""
        self._foreground_claims = 0
        self._resume_background()

    def _pause_background(self) -> None:
        manager = self._chiptunes_manager
        if manager is None or not manager.enabled:
            return
        manager.pause()
        self._background_paused = True
        logger.debug("Audio focus: paused background music", extra={"claims": self._foreground_claims})

    def _resume_background(self) -> None:
        if not self._background_paused:
            return
        if self._chiptunes_manager is not None and self._chiptunes_manager.enabled:
            self._chiptunes_manager.resume()
            logger.debug("Audio focus: resumed background music")
        self._background_paused = False

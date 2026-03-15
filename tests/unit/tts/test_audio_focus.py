"""Characterization tests for teleclaude.tts.audio_focus."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from teleclaude.tts.audio_focus import AudioFocusCoordinator


def _manager(*, enabled: bool = True, is_playing: bool = True) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled, is_playing=is_playing, pause=Mock(), resume=Mock())


def test_claim_foreground_pauses_background_only_on_first_claim() -> None:
    manager = _manager()
    coordinator = AudioFocusCoordinator()
    coordinator.set_chiptunes_manager(manager)

    coordinator.claim_foreground()
    coordinator.claim_foreground()

    assert coordinator.active_claims == 2
    manager.pause.assert_called_once_with()


def test_release_foreground_resumes_after_last_claim_drains() -> None:
    manager = _manager()
    coordinator = AudioFocusCoordinator()
    coordinator.set_chiptunes_manager(manager)
    coordinator.claim_foreground()
    coordinator.claim_foreground()

    coordinator.release_foreground()
    manager.resume.assert_not_called()
    coordinator.release_foreground()

    assert coordinator.active_claims == 0
    manager.resume.assert_called_once_with()


def test_on_background_state_change_reapplies_pause_for_active_claims() -> None:
    manager = _manager()
    coordinator = AudioFocusCoordinator()
    coordinator.set_chiptunes_manager(manager)
    coordinator.claim_foreground()
    manager.pause.reset_mock()

    coordinator.on_background_state_change()

    manager.pause.assert_called_once_with()


def test_cancel_background_resume_prevents_resume_on_release() -> None:
    manager = _manager()
    coordinator = AudioFocusCoordinator()
    coordinator.set_chiptunes_manager(manager)
    coordinator.claim_foreground()

    coordinator.cancel_background_resume()
    coordinator.release_foreground()

    manager.resume.assert_not_called()

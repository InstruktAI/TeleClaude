"""Characterization tests for teleclaude.tts.backends.macos_say."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from teleclaude.tts.backends.macos_say import MacOSSayBackend


def test_speak_runs_say_with_voice_flag_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", run)

    assert MacOSSayBackend().speak("hello", "Samantha") is True
    run.assert_called_once_with(["say", "-v", "Samantha", "hello"], check=True, capture_output=True, timeout=300)


def test_speak_returns_false_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(side_effect=subprocess.TimeoutExpired(cmd="say", timeout=300))
    monkeypatch.setattr(subprocess, "run", run)

    assert MacOSSayBackend().speak("hello", None) is False

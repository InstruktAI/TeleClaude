"""Characterization tests for teleclaude.tts.backends.pyttsx3_tts."""

from __future__ import annotations

import sys
import types
from unittest.mock import Mock, patch

from teleclaude.tts.backends.pyttsx3_tts import Pyttsx3Backend


def test_speak_configures_engine_and_runs_utterance() -> None:
    engine = Mock()
    pyttsx3_module = types.ModuleType("pyttsx3")
    pyttsx3_module.init = Mock(return_value=engine)

    with patch.dict(sys.modules, {"pyttsx3": pyttsx3_module}):
        assert Pyttsx3Backend().speak("hello", None) is True

    engine.setProperty.assert_any_call("rate", 180)
    engine.setProperty.assert_any_call("volume", 0.8)
    engine.say.assert_called_once_with("hello")
    engine.runAndWait.assert_called_once_with()


def test_speak_returns_false_when_import_fails() -> None:
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "pyttsx3":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        assert Pyttsx3Backend().speak("hello", None) is False

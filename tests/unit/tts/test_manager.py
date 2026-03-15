"""Characterization tests for teleclaude.tts.manager."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.tts.manager as tts_manager
from teleclaude.config import TTSConfig, TTSEventConfig, TTSServiceConfig, TTSServiceVoiceConfig
from teleclaude.core.events import AgentHookEvents
from teleclaude.core.origins import InputOrigin
from teleclaude.core.voice_assignment import VoiceConfig


def _config() -> TTSConfig:
    return TTSConfig(
        enabled=True,
        service_priority=["openai", "macos"],
        events={"session_start": TTSEventConfig(enabled=True, message="Session started.")},
        services={
            "openai": TTSServiceConfig(
                enabled=True,
                voices=[
                    TTSServiceVoiceConfig(name="Nova", voice_id="nova"),
                    TTSServiceVoiceConfig(name="Alloy", voice_id="alloy"),
                ],
            ),
            "macos": TTSServiceConfig(enabled=True, voices=None),
        },
    )


async def test_get_random_voice_for_session_respects_priority_and_in_use_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tts_manager.config, "tts", _config())
    monkeypatch.setattr(tts_manager.db, "get_voices_in_use", AsyncMock(return_value={("openai", "nova")}))
    monkeypatch.setattr(tts_manager.random, "choice", lambda seq: seq[0])
    manager = tts_manager.TTSManager()

    result = await manager.get_random_voice_for_session()

    assert result == ("openai", "alloy")


async def test_trigger_event_skips_non_terminal_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_manager.config, "tts", _config())
    monkeypatch.setattr(
        tts_manager.db,
        "get_session",
        AsyncMock(return_value=SimpleNamespace(last_input_origin=InputOrigin.TELEGRAM.value)),
    )
    manager = tts_manager.TTSManager()

    assert await manager.trigger_event(AgentHookEvents.AGENT_SESSION_START, "session-1") is False


async def test_speak_enqueues_assigned_voice_for_terminal_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_manager.config, "tts", _config())
    monkeypatch.setattr(
        tts_manager.db,
        "get_session",
        AsyncMock(return_value=SimpleNamespace(last_input_origin=InputOrigin.TERMINAL.value)),
    )
    manager = tts_manager.TTSManager()
    enqueue = AsyncMock()
    monkeypatch.setattr(manager, "_get_or_assign_voice", AsyncMock(return_value=VoiceConfig("openai", "nova")))
    monkeypatch.setattr(manager, "_enqueue_speech", enqueue)

    result = await manager.speak("hello", "session-1")

    assert result is True
    enqueue.assert_awaited_once_with("hello", [("openai", "nova")], "session-1", "openai")


async def test_run_speech_job_promotes_fallback_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = tts_manager.TTSManager()
    monkeypatch.setattr(
        tts_manager,
        "run_tts_with_lock_async",
        AsyncMock(return_value=(True, "macos", "macos")),
    )
    assign_voice = AsyncMock()
    monkeypatch.setattr(tts_manager.db, "assign_voice", assign_voice)
    job = tts_manager._SpeechJob(
        text="hello",
        service_chain=[("openai", "nova"), ("macos", None)],
        session_id="session-1",
        primary_service="openai",
    )

    await manager._run_speech_job(job)

    assign_voice.assert_awaited_once_with("session-1", VoiceConfig(service_name="macos", voice="macos"))

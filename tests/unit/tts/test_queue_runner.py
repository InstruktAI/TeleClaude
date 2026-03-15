"""Characterization tests for teleclaude.tts.queue_runner."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.tts.queue_runner as queue_runner


def test_run_tts_with_lock_returns_first_successful_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(speak=lambda text, voice: True)
    monkeypatch.setattr(
        queue_runner.backends,
        "get_backend",
        lambda service_name: None if service_name == "missing" else backend,
    )

    result = queue_runner.run_tts_with_lock(
        "hello",
        [("missing", None), ("openai", "nova")],
        "session-1",
    )

    assert result == (True, "openai", "nova")


def test_run_tts_with_lock_returns_failure_after_all_backends_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(speak=lambda text, voice: False)
    monkeypatch.setattr(queue_runner.backends, "get_backend", lambda service_name: backend)

    result = queue_runner.run_tts_with_lock(
        "hello",
        [("openai", "nova"), ("macos", None)],
        "session-1",
    )

    assert result == (False, None, None)


async def test_run_tts_with_lock_async_delegates_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    to_thread = AsyncMock(return_value=(True, "openai", "nova"))
    monkeypatch.setattr(queue_runner.asyncio, "to_thread", to_thread)

    result = await queue_runner.run_tts_with_lock_async("hello", [("openai", "nova")], "session-1")

    assert result == (True, "openai", "nova")
    to_thread.assert_awaited_once_with(queue_runner.run_tts_with_lock, "hello", [("openai", "nova")], "session-1")

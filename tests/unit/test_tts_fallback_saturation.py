"""Tests for TTS fallback chain saturation filtering.

Verifies that trigger_event builds a complete fallback chain that:
- Skips saturated providers (all voices in use)
- Includes all non-saturated providers in priority order
- Always puts the session's assigned voice first
- Handles services with no voice list (provider-name sentinel)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.config import TTSConfig, TTSEventConfig, TTSServiceConfig, TTSServiceVoiceConfig
from teleclaude.core.events import AgentHookEvents
from teleclaude.core.voice_assignment import VoiceConfig


def _make_manager(
    service_priority: list[str],
    services: dict[str, TTSServiceConfig],
) -> "TTSManager":
    """Build a TTSManager with injected config (no disk I/O)."""
    from teleclaude.tts.manager import TTSManager

    mgr = TTSManager.__new__(TTSManager)
    mgr.enabled = True
    mgr.tts_config = TTSConfig(
        enabled=True,
        service_priority=service_priority,
        events={"session_start": TTSEventConfig(enabled=True, message="hello")},
        services=services,
    )
    return mgr


def _voice(name: str, voice_id: str | None = None) -> TTSServiceVoiceConfig:
    return TTSServiceVoiceConfig(name=name, voice_id=voice_id)


def _service(enabled: bool = True, voices: list[TTSServiceVoiceConfig] | None = None) -> TTSServiceConfig:
    return TTSServiceConfig(enabled=enabled, voices=voices)


# ── fixtures ──────────────────────────────────────────────────────────────

SIX_PROVIDERS = ["elevenlabs", "openai", "macos", "pyttsx3", "cartesia", "azure"]


def _six_provider_services() -> dict[str, TTSServiceConfig]:
    return {
        "elevenlabs": _service(voices=[_voice("alice", "el-1"), _voice("bob", "el-2")]),
        "openai": _service(voices=[_voice("nova"), _voice("echo")]),
        "macos": _service(),  # no voice list → provider-name sentinel
        "pyttsx3": _service(),
        "cartesia": _service(voices=[_voice("clara", "ca-1")]),
        "azure": _service(voices=[_voice("aria", "az-1"), _voice("guy", "az-2")]),
    }


# ── helpers ───────────────────────────────────────────────────────────────


def _mock_session(origin: str = "terminal") -> MagicMock:
    s = MagicMock()
    s.last_input_origin = origin
    return s


async def _trigger(
    manager: "TTSManager",
    session_id: str,
    assigned_voice: VoiceConfig,
    voices_in_use: set[tuple[str, str]],
) -> list[tuple[str, str | None]]:
    """Call trigger_event and capture the service_chain passed to the TTS runner."""
    captured_chains: list[list[tuple[str, str | None]]] = []

    async def _capture_tts(text, chain, sid):
        captured_chains.append(chain)
        return (True, chain[0][0], chain[0][1])

    mock_task = MagicMock()
    mock_task.result.return_value = (True, assigned_voice.service_name, assigned_voice.voice)

    with (
        patch("teleclaude.tts.manager.db") as mock_db,
        patch("teleclaude.tts.manager.run_tts_with_lock_async", side_effect=_capture_tts) as mock_run,
        patch("teleclaude.tts.manager.asyncio") as mock_asyncio,
    ):
        mock_db.get_session = AsyncMock(return_value=_mock_session())
        mock_db.get_voice = AsyncMock(return_value=assigned_voice)
        mock_db.get_voices_in_use = AsyncMock(return_value=voices_in_use)

        # Make create_task return a mock that captures the done callback
        task_mock = MagicMock()
        mock_asyncio.create_task = MagicMock(side_effect=lambda coro: (task_mock, coro.close())[0])

        result = await manager.trigger_event(
            AgentHookEvents.AGENT_SESSION_START,
            session_id,
            text="test speech",
        )

    assert result is True, "trigger_event should return True"
    # The chain is passed to run_tts_with_lock_async
    assert mock_run.call_count == 1
    _, call_args, _ = mock_run.mock_calls[0]
    return call_args[1]  # service_chain argument


# ── tests ─────────────────────────────────────────────────────────────────


class TestFallbackChainSaturation:
    """Verify the full fallback chain respects saturation across all providers."""

    @pytest.mark.asyncio
    async def test_no_saturation_includes_all_providers(self) -> None:
        """With nothing saturated, chain includes primary + all 5 fallbacks."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="elevenlabs", voice="el-1")

        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=set())

        # Primary first, then all 5 remaining providers
        assert chain[0] == ("elevenlabs", "el-1")
        fallback_services = [svc for svc, _ in chain[1:]]
        assert fallback_services == ["openai", "macos", "pyttsx3", "cartesia", "azure"]

    @pytest.mark.asyncio
    async def test_saturated_provider_skipped_others_remain(self) -> None:
        """Saturating one provider skips it, rest of chain stays intact."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="elevenlabs", voice="el-1")

        # Saturate openai: both voices in use
        in_use = {("openai", "nova"), ("openai", "echo")}
        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=in_use)

        services = [svc for svc, _ in chain]
        assert "openai" not in services
        # All others present
        assert services == ["elevenlabs", "macos", "pyttsx3", "cartesia", "azure"]

    @pytest.mark.asyncio
    async def test_multiple_saturated_providers_all_skipped(self) -> None:
        """Saturating 3 of 6 providers leaves only the 3 non-saturated ones."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="elevenlabs", voice="el-1")

        # Saturate openai + cartesia + azure
        in_use = {
            ("openai", "nova"),
            ("openai", "echo"),
            ("cartesia", "ca-1"),
            ("azure", "az-1"),
            ("azure", "az-2"),
        }
        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=in_use)

        services = [svc for svc, _ in chain]
        assert services == ["elevenlabs", "macos", "pyttsx3"]

    @pytest.mark.asyncio
    async def test_voiceless_service_saturated_when_sentinel_in_use(self) -> None:
        """Services with no voice list (macos, pyttsx3) use provider-name sentinel."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="elevenlabs", voice="el-1")

        # Saturate macos (sentinel: ("macos", "macos"))
        in_use = {("macos", "macos")}
        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=in_use)

        services = [svc for svc, _ in chain]
        assert "macos" not in services
        # pyttsx3 still available (its sentinel not in use)
        assert "pyttsx3" in services

    @pytest.mark.asyncio
    async def test_partial_saturation_picks_available_voice(self) -> None:
        """When some voices of a provider are in use, only available ones can be chosen."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="elevenlabs", voice="el-1")

        # One of openai's two voices is taken
        in_use = {("openai", "nova")}
        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=in_use)

        # openai should still appear (has "echo" available)
        openai_entries = [(svc, v) for svc, v in chain if svc == "openai"]
        assert len(openai_entries) == 1
        assert openai_entries[0][1] == "echo"  # only available voice

    @pytest.mark.asyncio
    async def test_all_fallbacks_saturated_chain_is_primary_only(self) -> None:
        """If every fallback provider is saturated, chain has only the primary voice."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="elevenlabs", voice="el-1")

        # Saturate everything except the primary
        in_use = {
            ("openai", "nova"),
            ("openai", "echo"),
            ("macos", "macos"),
            ("pyttsx3", "pyttsx3"),
            ("cartesia", "ca-1"),
            ("azure", "az-1"),
            ("azure", "az-2"),
        }
        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=in_use)

        assert chain == [("elevenlabs", "el-1")]

    @pytest.mark.asyncio
    async def test_primary_voice_always_first_regardless_of_saturation(self) -> None:
        """The session's assigned voice is always position 0, even if it appears in voices_in_use."""
        mgr = _make_manager(SIX_PROVIDERS, _six_provider_services())
        assigned = VoiceConfig(service_name="openai", voice="nova")

        # The assigned voice IS in voices_in_use (it's this session's own voice)
        in_use = {("openai", "nova")}
        chain = await _trigger(mgr, "sess-1", assigned, voices_in_use=in_use)

        assert chain[0] == ("openai", "nova")
        # openai should NOT appear again in fallbacks (it's the primary)
        openai_fallbacks = [svc for svc, _ in chain[1:] if svc == "openai"]
        assert openai_fallbacks == []

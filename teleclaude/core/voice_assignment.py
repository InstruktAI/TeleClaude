"""Voice assignment for TeleClaude sessions.

Assigns random TTS voices to new sessions for distinct AI personalities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.tts.manager import TTSManager

logger = get_logger(__name__)


@dataclass
class VoiceConfig:
    """Voice configuration for a session (service-specific).

    Attributes:
        service_name: TTS service (elevenlabs, openai, macos, pyttsx3, qwen3)
        voice: Opaque voice identifier (ID, name, or empty string depending on service)
    """

    service_name: str
    voice: str


# Lazy-initialized TTS manager (avoids circular import)
_tts_manager: TTSManager | None = None


def _get_tts_manager() -> TTSManager:
    """Get or create TTS manager instance (lazy import to avoid circular dependency)."""
    global _tts_manager  # noqa: PLW0603 - singleton pattern
    if _tts_manager is None:
        from teleclaude.tts.manager import TTSManager

        _tts_manager = TTSManager()
    return _tts_manager


async def get_random_voice() -> VoiceConfig | None:
    """Get a random voice assignment for a session.

    Returns:
        VoiceConfig with (service_name, voice) or None if no voices configured.
    """
    manager = _get_tts_manager()
    voice_assignment = await manager.get_random_voice_for_session()
    if voice_assignment:
        service_name, voice_param = voice_assignment
        logger.info("Assigned voice: %s from service %s", voice_param, service_name)
        return VoiceConfig(service_name=service_name, voice=voice_param or "")
    return None


def get_voice_env_vars(voice: VoiceConfig) -> dict[str, str]:
    """Convert VoiceConfig to environment variables dict.

    Args:
        voice: Voice configuration to convert.

    Returns:
        Dict of environment variable names to values.
    """
    env_vars = {}

    if voice.service_name == "elevenlabs":
        env_vars["ELEVENLABS_VOICE_ID"] = voice.voice
    elif voice.service_name == "macos":
        env_vars["MACOS_VOICE"] = voice.voice
    elif voice.service_name == "openai":
        env_vars["OPENAI_VOICE"] = voice.voice
    # pyttsx3 and qwen3 don't use voice parameters

    return env_vars

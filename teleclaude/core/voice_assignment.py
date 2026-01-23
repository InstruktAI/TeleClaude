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
        service_name: TTS service (elevenlabs, openai, macos, pyttsx3)
        voice_name: Voice ID or name for the service
    """

    service_name: str
    voice_name: str


# Lazy-initialized TTS manager (avoids circular import)
_tts_manager: TTSManager | None = None


def _get_tts_manager() -> TTSManager:
    """Get or create TTS manager instance (lazy import to avoid circular dependency)."""
    global _tts_manager  # noqa: PLW0603 - singleton pattern
    if _tts_manager is None:
        from teleclaude.tts.manager import TTSManager

        _tts_manager = TTSManager()
    return _tts_manager


def get_random_voice() -> VoiceConfig | None:
    """Get a random voice assignment for a session.

    Returns:
        VoiceConfig with (service_name, voice_name) or None if no voices configured.
    """
    manager = _get_tts_manager()
    voice_assignment = manager.get_random_voice_for_session()
    if voice_assignment:
        service_name, voice_name = voice_assignment
        logger.info("Assigned voice: %s from service %s", voice_name, service_name)
        return VoiceConfig(service_name=service_name, voice_name=voice_name or "")
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
        env_vars["ELEVENLABS_VOICE_ID"] = voice.voice_name
    elif voice.service_name == "macos":
        env_vars["MACOS_VOICE"] = voice.voice_name
    elif voice.service_name == "openai":
        env_vars["OPENAI_VOICE"] = voice.voice_name
    # pyttsx3 doesn't use voice parameters

    return env_vars

"""Voice configuration for TeleClaude sessions and its environment-variable form."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VoiceConfig:
    """Voice configuration for a session (service-specific).

    Attributes:
        service_name: TTS service (elevenlabs, openai, macos, pyttsx3, qwen3)
        voice: Opaque voice identifier (ID, name, or empty string depending on service)
    """

    service_name: str
    voice: str


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

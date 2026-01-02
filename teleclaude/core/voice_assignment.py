"""Voice assignment for TeleClaude sessions.

Assigns random TTS voices to new sessions for distinct AI personalities.
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

VOICES_CONFIG_PATH = Path.home() / ".claude" / "voices.json"


@dataclass
class VoiceConfig:
    """Voice configuration for a session."""

    name: str
    elevenlabs_id: str
    macos_voice: str
    openai_voice: str


def load_voices() -> list[VoiceConfig]:
    """Load voice configurations from JSON file.

    Returns:
        List of VoiceConfig objects, empty list if file not found or invalid.
    """
    if not VOICES_CONFIG_PATH.exists():
        logger.warning("Voice config not found: %s", VOICES_CONFIG_PATH)
        return []

    try:
        with open(VOICES_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)  # type: ignore[misc]

        voices = []
        for v in data.get("voices", []):  # type: ignore[misc]
            voices.append(
                VoiceConfig(
                    name=v.get("name", "Unknown"),  # type: ignore[misc]
                    elevenlabs_id=v.get("elevenlabs_id", ""),  # type: ignore[misc]
                    macos_voice=v.get("macos_voice", ""),  # type: ignore[misc]
                    openai_voice=v.get("openai_voice", ""),  # type: ignore[misc]
                )
            )
        logger.debug("Loaded %d voices from config", len(voices))
        return voices

    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in voice config: %s", e)
        return []
    except Exception as e:
        logger.error("Failed to load voice config: %s", e)
        return []


def get_random_voice() -> VoiceConfig | None:
    """Get a random voice configuration.

    Returns:
        Random VoiceConfig, or None if no voices configured.
    """
    voices = load_voices()
    if not voices:
        return None

    voice = random.choice(voices)
    logger.info("Assigned voice: %s", voice.name)
    return voice


def get_voice_env_vars(voice: VoiceConfig) -> dict[str, str]:
    """Convert VoiceConfig to environment variables dict.

    Args:
        voice: Voice configuration to convert.

    Returns:
        Dict of environment variable names to values.
    """
    env_vars = {}

    if voice.elevenlabs_id:
        env_vars["ELEVENLABS_VOICE_ID"] = voice.elevenlabs_id

    if voice.macos_voice:
        env_vars["MACOS_VOICE"] = voice.macos_voice

    if voice.openai_voice:
        env_vars["OPENAI_VOICE"] = voice.openai_voice

    return env_vars

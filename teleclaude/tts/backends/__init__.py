"""TTS backends - modular speech synthesis implementations."""

from teleclaude.tts.backends.elevenlabs import ElevenLabsBackend
from teleclaude.tts.backends.macos_say import MacOSSayBackend
from teleclaude.tts.backends.openai_tts import OpenAITTSBackend
from teleclaude.tts.backends.pyttsx3_tts import Pyttsx3Backend

BACKENDS = {
    "macos": MacOSSayBackend(),
    "elevenlabs": ElevenLabsBackend(),
    "openai": OpenAITTSBackend(),
    "pyttsx3": Pyttsx3Backend(),
}


def get_backend(service_name: str):
    """Get backend by service name."""
    return BACKENDS.get(service_name)

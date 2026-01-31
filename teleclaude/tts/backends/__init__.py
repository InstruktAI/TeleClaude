"""TTS backends - modular speech synthesis implementations."""

import sys
from typing import Protocol

from teleclaude.tts.backends.elevenlabs import ElevenLabsBackend
from teleclaude.tts.backends.openai_tts import OpenAITTSBackend
from teleclaude.tts.backends.pyttsx3_tts import Pyttsx3Backend


class TTSBackend(Protocol):
    """Common interface for all TTS backends."""

    def speak(self, text: str, voice: str | None = None, /) -> bool: ...


BACKENDS: dict[str, TTSBackend] = {
    "elevenlabs": ElevenLabsBackend(),
    "openai": OpenAITTSBackend(),
    "pyttsx3": Pyttsx3Backend(),
}

if sys.platform == "darwin":
    from teleclaude.tts.backends.macos_say import MacOSSayBackend
    from teleclaude.tts.backends.qwen3_tts import Qwen3TTSBackend

    BACKENDS["macos"] = MacOSSayBackend()
    BACKENDS["qwen3"] = Qwen3TTSBackend()


def get_backend(service_name: str):
    """Get backend by service name."""
    return BACKENDS.get(service_name)

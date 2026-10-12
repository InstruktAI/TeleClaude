"""The TTS backend registry: the built-in backends and the lookup that also resolves MLX services."""

import sys
from pathlib import Path
from typing import Protocol

from teleclaude.tts.backends.elevenlabs import ElevenLabsBackend
from teleclaude.tts.backends.mlx_registry import mlx_backend_for
from teleclaude.tts.backends.openai_tts import OpenAITTSBackend
from teleclaude.tts.backends.pyttsx3_tts import Pyttsx3Backend


class TTSBackend(Protocol):
    """Common interface for all TTS backends."""

    can_render: bool

    def speak(self, text: str, voice: str | None = None, /) -> bool:
        """Synthesize and play speech. Returns True on success."""
        raise NotImplementedError

    def render(self, text: str, voice: str | None, out_dir: Path) -> Path | None:
        """Synthesize speech to a file in ``out_dir`` without playing it.

        Returns the rendered file path, or ``None`` when rendering is
        unsupported or fails. ``can_render`` tells a caller whether to try.
        """
        raise NotImplementedError


BACKENDS: dict[str, TTSBackend] = {
    "elevenlabs": ElevenLabsBackend(),
    "openai": OpenAITTSBackend(),
    "pyttsx3": Pyttsx3Backend(),
}

if sys.platform == "darwin":
    from teleclaude.tts.backends.macos_say import MacOSSayBackend

    BACKENDS["macos"] = MacOSSayBackend()


def get_backend(service_name: str):  # type: ignore[no-untyped-def]
    """Get backend by service name: a built-in, else the service's MLX backend when it is enabled."""
    return BACKENDS.get(service_name) or mlx_backend_for(service_name)

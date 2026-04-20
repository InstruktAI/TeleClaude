"""STT backends — modular speech-to-text implementations."""

import sys
from typing import Protocol

from teleclaude.stt.backends.openai_whisper import OpenAIWhisperBackend


class STTBackend(Protocol):
    """Common interface for all STT backends."""

    async def transcribe(self, audio_file_path: str, language: str | None = None, /) -> str:
        """Transcribe an audio file to text."""
        raise NotImplementedError


BACKENDS: dict[str, STTBackend] = {
    "openai": OpenAIWhisperBackend(),
}

if sys.platform == "darwin":
    try:
        from teleclaude.stt.backends.mlx_parakeet import MLXParakeetBackend

        BACKENDS["parakeet"] = MLXParakeetBackend()
    except Exception:
        from instrukt_ai_logging import get_logger

        get_logger(__name__).warning("Parakeet STT backend unavailable", exc_info=True)


def get_backend(service_name: str) -> STTBackend | None:
    """Get backend by service name."""
    return BACKENDS.get(service_name)

"""STT backends — modular speech-to-text implementations."""

import sys
from typing import Protocol

from teleclaude.stt.backends.openai_whisper import OpenAIWhisperBackend


class STTBackend(Protocol):
    """Common interface for all STT backends."""

    async def transcribe(self, audio_file_path: str, language: str | None = None, /) -> str: ...


BACKENDS: dict[str, STTBackend] = {
    "openai": OpenAIWhisperBackend(),
}

if sys.platform == "darwin":
    try:
        from teleclaude.stt.backends.mlx_parakeet import MLXParakeetBackend

        BACKENDS["parakeet"] = MLXParakeetBackend()
    except Exception:  # noqa: BLE001 - import or config validation failure; skip gracefully
        import logging

        logging.getLogger(__name__).warning("Parakeet STT backend unavailable", exc_info=True)


def get_backend(service_name: str) -> STTBackend | None:
    """Get backend by service name."""
    return BACKENDS.get(service_name)

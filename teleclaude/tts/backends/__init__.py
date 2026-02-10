"""TTS backends - modular speech synthesis implementations."""

import sys
from typing import Protocol

from instrukt_ai_logging import get_logger

from teleclaude.tts.backends.elevenlabs import ElevenLabsBackend
from teleclaude.tts.backends.openai_tts import OpenAITTSBackend
from teleclaude.tts.backends.pyttsx3_tts import Pyttsx3Backend

logger = get_logger(__name__)


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

    BACKENDS["macos"] = MacOSSayBackend()

    # Register MLX TTS backends for any config service that has a model field set
    try:
        from teleclaude.config import config
        from teleclaude.tts.backends.mlx_tts import MLXTTSBackend

        if config.tts and config.tts.services:
            for service_name, service_cfg in config.tts.services.items():
                if service_name in BACKENDS:
                    continue
                if service_cfg.model:
                    try:
                        BACKENDS[service_name] = MLXTTSBackend(service_name, service_cfg.model, service_cfg.params)
                        logger.info("Registered MLX TTS backend: %s (model=%s)", service_name, service_cfg.model)
                    except Exception:  # noqa: BLE001 - config or model validation failure; skip gracefully
                        logger.warning("MLX TTS backend '%s' failed to initialize", service_name, exc_info=True)
    except Exception:  # noqa: BLE001 - mlx_audio or config not available
        logger.warning("MLX TTS backends unavailable", exc_info=True)


def get_backend(service_name: str):
    """Get backend by service name."""
    return BACKENDS.get(service_name)

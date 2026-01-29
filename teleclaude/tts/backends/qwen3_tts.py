"""Qwen3 TTS backend - local MLX-based text-to-speech."""

import tempfile

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
DEFAULT_VOICE = "serena"


class Qwen3TTSBackend:
    """Local TTS using mlx-audio with Qwen3 model."""

    def __init__(self):
        self._model = None

    def _ensure_model(self):
        """Lazy-load the model on first use."""
        if self._model is not None:
            return True
        try:
            from mlx_audio.tts.utils import load_model

            self._model = load_model(DEFAULT_MODEL)
            logger.info("Qwen3 TTS model loaded: %s", DEFAULT_MODEL)
            return True
        except ImportError:
            logger.debug("mlx-audio library not installed")
            return False
        except Exception as e:
            logger.error("Failed to load Qwen3 TTS model: %s", e)
            return False

    def speak(self, text: str, voice_name: str | None = None) -> bool:
        """
        Speak text using Qwen3 TTS via mlx-audio.

        Args:
            text: Text to speak
            voice_name: Voice name (e.g., "serena", "ryan"). Falls back to DEFAULT_VOICE.

        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_model():
            return False

        try:
            from mlx_audio.tts.generate import generate_audio

            voice = voice_name or DEFAULT_VOICE

            with tempfile.TemporaryDirectory() as tmp_dir:
                prefix = f"{tmp_dir}/tts_output"
                generate_audio(
                    model=self._model,
                    text=text,
                    voice=voice,
                    file_prefix=prefix,
                    play=True,
                    verbose=False,
                )

            logger.debug("Qwen3 TTS: spoke %d chars", len(text))
            return True
        except Exception as e:
            logger.error("Qwen3 TTS failed: %s", e)
            return False

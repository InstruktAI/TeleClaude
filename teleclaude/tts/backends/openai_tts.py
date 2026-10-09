"""OpenAI TTS backend - high-quality voice synthesis."""

import os
import tempfile
from pathlib import Path

from instrukt_ai_logging import get_logger
from openai import OpenAI
from openai._legacy_response import HttpxBinaryResponseContent

from teleclaude.config.machine import config
from teleclaude.tts.backends._local_play import play_file

logger = get_logger(__name__)


class OpenAITTSBackend:
    """OpenAI TTS using gpt-4o-mini-tts model."""

    can_render = True

    def _create_speech(self, text: str, voice: str) -> HttpxBinaryResponseContent | None:
        """Call the OpenAI speech API. Returns the response, or None if unavailable."""
        services = config.tts.services if config.tts else None
        service = services.get("openai") if services else None
        api_key = service.api_key if service else None
        if not api_key:
            logger.debug("tts.services.openai.api_key not set")
            return None
        client = OpenAI(api_key=api_key)
        return client.audio.speech.create(model="gpt-4o-mini-tts", voice=voice, input=text)

    def render(self, text: str, voice: str | None, out_dir: Path) -> Path | None:
        """Render text to an MP3 file in ``out_dir`` without playing it."""
        try:
            response = self._create_speech(text, voice or "nova")
            if response is None:
                return None
            out_path = out_dir / "reply.mp3"
            response.write_to_file(str(out_path))
            return out_path
        except ImportError:
            logger.debug("openai library not installed")
            return None
        except Exception as e:
            logger.debug(f"OpenAI TTS render failed: {e}")
            return None

    def speak(self, text: str, voice_name: str | None = None) -> bool:
        """
        Speak text using OpenAI TTS API.

        Args:
            text: Text to speak
            voice_name: OpenAI voice name (e.g., "nova", "onyx")

        Returns:
            True if successful, False otherwise
        """
        try:
            services = config.tts.services if config.tts else None
            service = services.get("openai") if services else None
            api_key = service.api_key if service else None
            if not api_key:
                logger.debug("tts.services.openai.api_key not set")
                return False

            voice = voice_name or "nova"

            client = OpenAI(api_key=api_key)
            response = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=voice,
                input=text,
            )

            # Write to temp and play
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                response.write_to_file(tmp_path)
                if not play_file(Path(tmp_path)):
                    return False
                logger.debug(f"OpenAI: spoke {len(text)} chars with voice {voice}")
                return True
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except ImportError:
            logger.debug("openai library not installed")
            return False
        except Exception as e:
            logger.debug(f"OpenAI TTS failed: {e}")
            return False

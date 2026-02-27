"""OpenAI TTS backend - high-quality voice synthesis."""

import os
import subprocess
import tempfile

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class OpenAITTSBackend:
    """OpenAI TTS using gpt-4o-mini-tts model."""

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
            from openai import OpenAI

            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.debug("OPENAI_API_KEY not set")
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
                subprocess.run(["afplay", tmp_path], check=True, capture_output=True, timeout=300)
                logger.debug(f"OpenAI: spoke {len(text)} chars with voice {voice}")
                return True
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except ImportError:
            logger.debug("openai library not installed")
            return False
        except FileNotFoundError:
            logger.debug("afplay command not found (not on macOS?)")
            return False
        except Exception as e:
            logger.debug(f"OpenAI TTS failed: {e}")
            return False

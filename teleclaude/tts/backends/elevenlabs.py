"""ElevenLabs backend - premium voice synthesis."""

import os

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class ElevenLabsBackend:
    """ElevenLabs TTS using Flash v2.5 model."""

    def speak(self, text: str, voice_id: str | None = None) -> bool:
        """
        Speak text using ElevenLabs API.

        Args:
            text: Text to speak
            voice_id: ElevenLabs voice ID

        Returns:
            True if successful, False otherwise
        """
        try:
            api_key = os.getenv("ELEVENLABS_API_KEY")
            if not api_key:
                logger.debug("ELEVENLABS_API_KEY not set")
                return False

            if not voice_id:
                logger.debug("ElevenLabs: no voice_id provided")
                return False

            # Lazy import: elevenlabs lives in the `tts` extra, provisioned on enable.
            from elevenlabs.client import ElevenLabs  # type: ignore[import-not-found]  # noqa: PLC0415
            from elevenlabs.play import play  # type: ignore[import-not-found]  # noqa: PLC0415

            client = ElevenLabs(api_key=api_key)
            audio = client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id="eleven_flash_v2_5",
                output_format="mp3_44100_128",
            )

            play(audio)
            logger.debug(f"ElevenLabs: spoke {len(text)} chars with voice {voice_id}")
            return True
        except ImportError:
            logger.debug("elevenlabs library not installed")
            return False
        except Exception as e:
            logger.debug(f"ElevenLabs failed: {e}")
            return False

"""ElevenLabs backend - premium voice synthesis."""

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config

logger = get_logger(__name__)


class ElevenLabsBackend:
    """ElevenLabs TTS using Flash v2.5 model."""

    can_render = True

    def _synthesize(self, text: str, voice_id: str) -> bytes | None:
        """Call the ElevenLabs API. Returns the audio bytes, or None if unavailable."""
        services = config.tts.services if config.tts else None
        service = services.get("elevenlabs") if services else None
        api_key = service.api_key if service else None
        if not api_key:
            logger.debug("tts.services.elevenlabs.api_key not set")
            return None

        # Lazy import: elevenlabs lives in the `tts` extra, provisioned on enable.
        from elevenlabs.client import ElevenLabs  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

        client = ElevenLabs(api_key=api_key)
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id="eleven_flash_v2_5",
            output_format="mp3_44100_128",
        )
        return b"".join(audio)

    def render(self, text: str, voice: str | None, out_dir: Path) -> Path | None:
        """Render text to an MP3 file in ``out_dir`` without playing it."""
        if not voice:
            logger.debug("ElevenLabs: no voice_id provided")
            return None
        try:
            audio_bytes = self._synthesize(text, voice)
            if audio_bytes is None:
                return None
            out_path = out_dir / "reply.mp3"
            out_path.write_bytes(audio_bytes)
            return out_path
        except ImportError:
            logger.debug("elevenlabs library not installed")
            return None
        except Exception as e:
            logger.debug(f"ElevenLabs render failed: {e}")
            return None

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
            services = config.tts.services if config.tts else None
            service = services.get("elevenlabs") if services else None
            api_key = service.api_key if service else None
            if not api_key:
                logger.debug("tts.services.elevenlabs.api_key not set")
                return False

            if not voice_id:
                logger.debug("ElevenLabs: no voice_id provided")
                return False

            # Lazy import: elevenlabs lives in the `tts` extra, provisioned on enable.
            # The ignore must hold both ways: `import-not-found` fires where the extra
            # is absent, and the ignore itself reads as unused where it is installed.
            from elevenlabs.client import ElevenLabs  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415
            from elevenlabs.play import play  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

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

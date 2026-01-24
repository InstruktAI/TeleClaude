"""pyttsx3 backend - offline TTS fallback."""

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class Pyttsx3Backend:
    """pyttsx3 offline TTS - always available fallback."""

    def speak(self, text: str, voice_name: str | None = None) -> bool:
        """
        Speak text using pyttsx3 (offline).

        Args:
            text: Text to speak
            voice_name: Unused (pyttsx3 uses system default)

        Returns:
            True if successful, False otherwise
        """
        try:
            import pyttsx3  # type: ignore[import-not-found]

            engine = pyttsx3.init()
            engine.setProperty("rate", 180)  # Words per minute
            engine.setProperty("volume", 0.8)  # Volume 0.0-1.0
            engine.say(text)
            engine.runAndWait()

            logger.debug(f"pyttsx3: spoke {len(text)} chars (offline)")
            return True
        except ImportError:
            logger.debug("pyttsx3 library not installed")
            return False
        except Exception as e:
            logger.debug(f"pyttsx3 failed: {e}")
            return False

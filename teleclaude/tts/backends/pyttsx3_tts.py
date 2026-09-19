"""pyttsx3 backend - offline TTS fallback."""

import importlib
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class Pyttsx3Backend:
    """pyttsx3 offline TTS - always available fallback."""

    can_render = True

    def render(self, text: str, voice: str | None, out_dir: Path) -> Path | None:
        """Render text to a WAV file in ``out_dir`` without playing it."""
        try:
            pyttsx3 = importlib.import_module("pyttsx3")
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            engine.setProperty("volume", 0.8)
            out_path = out_dir / "reply.wav"
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
        except ImportError:
            logger.debug("pyttsx3 library not installed")
            return None
        except Exception as e:
            logger.debug(f"pyttsx3 render failed: {e}")
            return None
        if not out_path.exists() or not out_path.stat().st_size:
            logger.error("pyttsx3: render produced no audio file")
            return None
        return out_path

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
            pyttsx3 = importlib.import_module("pyttsx3")
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

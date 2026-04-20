"""macOS say backend - native text-to-speech."""

import subprocess

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class MacOSSayBackend:
    """macOS native TTS using say command."""

    def speak(self, text: str, voice_name: str | None = None) -> bool:
        """
        Speak text using macOS say command.

        Args:
            text: Text to speak
            voice_name: macOS voice name (e.g., "Samantha (Enhanced)")

        Returns:
            True if successful, False otherwise
        """
        try:
            cmd = ["say"]
            if voice_name:
                cmd.extend(["-v", voice_name])
            cmd.append(text)

            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
            logger.debug(f"macOS say: spoke {len(text)} chars", extra={"voice": voice_name})
            return True
        except subprocess.TimeoutExpired:
            logger.error("macOS say: timeout", extra={"voice": voice_name})
            return False
        except FileNotFoundError:
            logger.error("macOS say: command not found (not on macOS?)")
            return False
        except Exception as e:
            logger.debug(f"macOS say failed: {e}", extra={"voice": voice_name})
            return False

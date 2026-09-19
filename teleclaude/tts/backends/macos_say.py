"""macOS say backend - native text-to-speech."""

import subprocess
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class MacOSSayBackend:
    """macOS native TTS using say command."""

    can_render = True

    def render(self, text: str, voice: str | None, out_dir: Path) -> Path | None:
        """Render text to an AIFF file in ``out_dir`` without playing it."""
        out_path = out_dir / "reply.aiff"
        cmd = ["say", "-o", str(out_path)]
        if voice:
            cmd.extend(["-v", voice])
        cmd.append(text)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            logger.error("macOS say: render timeout", extra={"voice": voice})
            return None
        except FileNotFoundError:
            logger.error("macOS say: command not found (not on macOS?)")
            return None
        except Exception as e:
            logger.debug(f"macOS say render failed: {e}", extra={"voice": voice})
            return None
        if not out_path.exists() or not out_path.stat().st_size:
            logger.error("macOS say: render produced no audio file", extra={"voice": voice})
            return None
        return out_path

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

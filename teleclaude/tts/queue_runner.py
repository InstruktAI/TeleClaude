"""TTS Queue Runner - ensures sequential playback with file locking."""

import asyncio
import fcntl
import tempfile
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.tts import backends

logger = get_logger(__name__)


def run_tts_with_lock(
    text: str,
    service_chain: list[tuple[str, str | None]],
    session_id: str,
) -> tuple[bool, str | None, str | None]:
    """
    Run TTS services with fallback while holding exclusive lock.

    Tries each service in order until one succeeds.

    Args:
        text: Text to speak
        service_chain: List of (service_name, voice_id_or_name) tuples
        session_id: Session ID for logging

    Returns:
        Tuple of (success, service_name, voice_param) for the first successful service.
    """
    # Use system /tmp for playback lock
    lock_dir = Path(tempfile.gettempdir()) / "teleclaude_tts"
    lock_dir.mkdir(exist_ok=True, parents=True)
    playback_lock = lock_dir / ".playback.lock"

    try:
        with open(playback_lock, "a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

            for service_name, voice_param in service_chain:
                logger.debug(
                    f"Trying TTS service: {service_name}",
                    extra={"session_id": session_id[:8]},
                )

                backend = backends.get_backend(service_name)
                if not backend:
                    logger.debug(
                        f"Backend not available: {service_name}",
                        extra={"session_id": session_id[:8]},
                    )
                    continue

                try:
                    if backend.speak(text, voice_param):
                        logger.debug(
                            f"TTS succeeded: {service_name}",
                            extra={"session_id": session_id[:8]},
                        )
                        return True, service_name, voice_param
                except Exception as e:
                    logger.debug(
                        f"TTS service failed: {service_name}: {e}",
                        extra={"session_id": session_id[:8]},
                    )
                    continue

                logger.debug(
                    f"TTS failed, trying next: {service_name}",
                    extra={"session_id": session_id[:8]},
                )

            logger.warning(
                "All TTS services failed",
                extra={"session_id": session_id[:8]},
            )
        return False, None, None
    except Exception as e:
        logger.error(
            f"TTS lock error: {e}",
            extra={"session_id": session_id[:8]},
        )
        return False, None, None


async def run_tts_with_lock_async(
    text: str,
    service_chain: list[tuple[str, str | None]],
    session_id: str,
) -> tuple[bool, str | None, str | None]:
    """Run TTS in a background thread to avoid blocking the event loop."""
    return await asyncio.to_thread(run_tts_with_lock, text, service_chain, session_id)

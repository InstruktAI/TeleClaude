"""The configured speech-to-text service chain."""

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.stt.backends import BACKENDS, STTBackend
from teleclaude.stt.errors import NoSTTServiceError, STTServiceUnavailableError, STTTranscriptionFailedError

logger = get_logger(__name__)
_NO_BACKENDS_MESSAGE = "No STT backends available"
_BACKENDS_FAILED_MESSAGE = "All STT backends failed: {errors}"
_TRANSCRIBED_LOG = "STT transcribed via %s: %d chars"
_BACKEND_UNAVAILABLE_LOG = "STT backend %s unavailable: %s"
_BACKEND_FAILED_LOG = "STT backend %s failed: %s"
_EMPTY_ERRORS = ""
_ERROR_DETAIL = "{name}: {error}"
_ERROR_SEPARATOR = "; "


def _get_service_chain() -> list[tuple[str, STTBackend]]:
    """Build the ordered STT chain from the effective enabled state and priority."""
    stt_cfg = config.stt
    if stt_cfg is None or not stt_cfg.enabled:
        return []
    chain: list[tuple[str, STTBackend]] = []
    for name in stt_cfg.service_priority or BACKENDS.keys():
        service_cfg = (stt_cfg.services or {}).get(name)
        if service_cfg is not None and not service_cfg.enabled:
            continue
        backend = BACKENDS.get(name)
        if backend:
            chain.append((name, backend))
    return chain


async def transcribe_voice(audio_file_path: str, language: str | None = None) -> str:
    """Transcribe audio using the configured backends in priority order.

    Raises:
        NoSTTServiceError: If no configured backend can run on this computer.
        STTTranscriptionFailedError: If available backends do not produce text.
    """
    chain = _get_service_chain()
    if not chain:
        raise NoSTTServiceError(_NO_BACKENDS_MESSAGE)

    errors: list[str] = []
    unavailable_errors: list[str] = []
    for name, backend in chain:
        try:
            text = await backend.transcribe(audio_file_path, language)
            if text:
                logger.info(_TRANSCRIBED_LOG, name, len(text))
                return text
        except STTServiceUnavailableError as error:
            detail = _ERROR_DETAIL.format(name=name, error=error)
            errors.append(detail)
            unavailable_errors.append(detail)
            logger.warning(_BACKEND_UNAVAILABLE_LOG, name, error)
        except Exception as error:
            errors.append(_ERROR_DETAIL.format(name=name, error=error))
            logger.warning(_BACKEND_FAILED_LOG, name, error)

    if len(unavailable_errors) == len(chain):
        raise NoSTTServiceError(_BACKENDS_FAILED_MESSAGE.format(errors=_ERROR_SEPARATOR.join(errors)))
    raise STTTranscriptionFailedError(
        _BACKENDS_FAILED_MESSAGE.format(errors=_ERROR_SEPARATOR.join(errors) or _EMPTY_ERRORS)
    )

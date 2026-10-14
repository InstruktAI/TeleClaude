"""Supplied-audio transcription API route."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import (
    AudioSTTFailureKind,
    AudioSTTFailureResponse,
    AudioSTTOkResponse,
    AudioSTTRequest,
    AudioSTTResponse,
    AudioSTTResponseStatus,
)
from teleclaude.core.integration.speech_to_text import (
    AudioSource,
    AudioSourceUnavailableError,
    MediaProberUnavailableError,
    UnsupportedAudioMediaError,
    transcribe_supplied_audio,
)
from teleclaude.stt.errors import NoSTTServiceError, STTTranscriptionFailedError

_AUDIO_API_PREFIX = "/api/audio"
_AUDIO_STT_ROUTE = "/stt"
_HTTP_UNAVAILABLE_STATUS = 503
_SOURCE_UNAVAILABLE_REASON = "source unavailable"
_UNSUPPORTED_MEDIA_REASON = "unsupported media"
_NO_SERVICE_REASON = "no speech-to-text service"
_TRANSCRIPTION_FAILED_REASON = "transcription failed"

router = APIRouter(prefix=_AUDIO_API_PREFIX, tags=["audio"])


@router.post(_AUDIO_STT_ROUTE, response_model=AudioSTTResponse)
async def transcribe_audio(
    body: AudioSTTRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> AudioSTTResponse:
    """Transcribe one supplied audio source on the daemon's computer."""
    source = AudioSource(url=body.url, path=Path(body.path) if body.path is not None else None)
    try:
        transcript = await transcribe_supplied_audio(source, body.language)
    except AudioSourceUnavailableError as error:
        return AudioSTTFailureResponse(
            status=AudioSTTResponseStatus.FAILED,
            failure_kind=AudioSTTFailureKind.SOURCE_UNAVAILABLE,
            reason=str(error) or _SOURCE_UNAVAILABLE_REASON,
        )
    except UnsupportedAudioMediaError as error:
        return AudioSTTFailureResponse(
            status=AudioSTTResponseStatus.FAILED,
            failure_kind=AudioSTTFailureKind.UNSUPPORTED_MEDIA,
            reason=str(error) or _UNSUPPORTED_MEDIA_REASON,
        )
    except NoSTTServiceError as error:
        return AudioSTTFailureResponse(
            status=AudioSTTResponseStatus.FAILED,
            failure_kind=AudioSTTFailureKind.NO_STT_SERVICE,
            reason=str(error) or _NO_SERVICE_REASON,
        )
    except STTTranscriptionFailedError as error:
        return AudioSTTFailureResponse(
            status=AudioSTTResponseStatus.FAILED,
            failure_kind=AudioSTTFailureKind.TRANSCRIPTION_FAILED,
            reason=str(error) or _TRANSCRIPTION_FAILED_REASON,
        )
    except MediaProberUnavailableError as error:
        raise HTTPException(status_code=_HTTP_UNAVAILABLE_STATUS, detail=str(error)) from error

    return AudioSTTOkResponse(status=AudioSTTResponseStatus.OK, transcript=transcript)

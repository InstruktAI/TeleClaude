"""Handler for telec audio stt."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from teleclaude.api_models import (
    AudioSTTFailureKind,
    AudioSTTOkResponse,
    AudioSTTRequest,
    AudioSTTResponse,
)
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import AUDIO
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.constants import (
    AUDIO_STT_FETCH_TIMEOUT_S,
    AUDIO_STT_INSPECTION_TIMEOUT_S,
    VOICE_TRANSCRIPTION_TIMEOUT_S,
)

__all__ = ["_handle_audio"]

_SOURCE_USAGE_ERROR = "Provide exactly one of --url or --path."
_UNUSABLE_RESPONSE_ERROR = "Error: the transcription service returned an unusable response."
_AUDIO_COMMAND = "audio"
_STT_SUBCOMMAND = "stt"
_MODEL_DUMP_MODE_JSON = "json"
_API_METHOD = "POST"
_API_PATH = "/api/audio/stt"
_CLIENT_TIMEOUT_MARGIN_S = 15.0
_REQUEST_TIMEOUT_S = (
    AUDIO_STT_FETCH_TIMEOUT_S
    + AUDIO_STT_INSPECTION_TIMEOUT_S
    + VOICE_TRANSCRIPTION_TIMEOUT_S
    + _CLIENT_TIMEOUT_MARGIN_S
)
_FAILURE_EXIT_STATUS: dict[AudioSTTFailureKind, int] = {
    AudioSTTFailureKind.SOURCE_UNAVAILABLE: 3,
    AudioSTTFailureKind.UNSUPPORTED_MEDIA: 4,
    AudioSTTFailureKind.NO_STT_SERVICE: 5,
    AudioSTTFailureKind.TRANSCRIPTION_FAILED: 6,
}
_RESPONSE_ADAPTER: TypeAdapter[AudioSTTResponse] = TypeAdapter(AudioSTTResponse)


def _handle_audio(args: list[str]) -> None:
    """Handle telec audio stt using the daemon's configured speech-to-text chain."""
    parsed = parse_command_args(AUDIO, args)
    url = parsed.value(F.FLAG_AUDIO_URL)
    path = parsed.value(F.FLAG_AUDIO_PATH)
    if (url is None) == (path is None):
        print(_SOURCE_USAGE_ERROR, file=sys.stderr)
        print(_usage(_AUDIO_COMMAND, _STT_SUBCOMMAND), file=sys.stderr)
        raise SystemExit(1)

    resolved_path = str(Path(path).expanduser().resolve()) if path is not None else None
    request = AudioSTTRequest(url=url, path=resolved_path, language=parsed.value(F.FLAG_AUDIO_LANGUAGE))
    result = tool_api_request(
        _API_METHOD,
        _API_PATH,
        json_body=request.model_dump(mode=_MODEL_DUMP_MODE_JSON),
        timeout=_REQUEST_TIMEOUT_S,
    )
    try:
        response = _RESPONSE_ADAPTER.validate_python(result)
    except ValidationError:
        print(_UNUSABLE_RESPONSE_ERROR, file=sys.stderr)
        raise SystemExit(1) from None

    if isinstance(response, AudioSTTOkResponse):
        print(response.transcript)
        return

    failure = response
    print(failure.reason, file=sys.stderr)
    raise SystemExit(_FAILURE_EXIT_STATUS[failure.failure_kind])

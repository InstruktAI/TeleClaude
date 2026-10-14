"""Application service for transcribing supplied audio."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from urllib.parse import ParseResult, urlparse

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    AUDIO_STT_FETCH_TIMEOUT_S,
    AUDIO_STT_INSPECTION_TIMEOUT_S,
    VOICE_TRANSCRIPTION_TIMEOUT_S,
)
from teleclaude.stt.chain import transcribe_voice
from teleclaude.stt.errors import NoSTTServiceError, STTTranscriptionFailedError

logger = get_logger(__name__)
_SOURCE_EXCLUSIVE_ERROR = "Exactly one audio source URL or path is required"
_FFPROBE_MISSING_ERROR = "ffprobe is required; install it with ffmpeg"
_UNREADABLE_PATH_ERROR = "Audio path is not a readable file: {path}"
_UNSUPPORTED_SCHEME_ERROR = "Audio URL must use http or https"
_FETCH_FAILED_LOG = "audio_source_fetch_failed"
_FETCHED_LOG = "audio_source_fetched"
_UNKNOWN_HOST = "unknown"
_HTTP_STATUS_REASON = "Audio source returned HTTP {status}"
_FETCH_TIMEOUT_REASON = "Audio source fetch timed out"
_FETCH_FAILED_REASON = "Audio source fetch failed ({error_type})"
_TEMPORARY_AUDIO_CLEANUP_FAILED_LOG = "temporary_audio_cleanup_failed"
_TEMPORARY_AUDIO_CLEANUP_FAILED_REASON = "Unable to remove temporary audio source"
_MISSING_PROBER_START_ERROR = "Unable to start required ffprobe"
_INSPECTION_TIMEOUT_ERROR = "Audio media inspection timed out after {timeout:g} seconds"
_UNSUPPORTED_STREAM_ERROR = "Source does not contain a decodable audio stream"
_TRANSCRIPTION_TIMEOUT_ERROR = "Transcription timed out after {timeout:g} seconds"
_GET_METHOD = "GET"
_FFPROBE_COMMAND = "ffprobe"
_HTTP_SCHEME = "http"
_HTTPS_SCHEME = "https"
_CONTENT_TYPE_HEADER = "content-type"
_HEADER_PARAMETER_SEPARATOR = ";"
_BINARY_WRITE_MODE = "wb"
_EMPTY_TEXT = ""
_EMPTY_SUFFIX = ""
_TEMP_DIR_PREFIX = "teleclaude-audio-stt-"
_HTTP_TIMEOUT_S = 10.0
_FFPROBE_ARGS = (
    "-v",
    "error",
    "-select_streams",
    "a",
    "-show_entries",
    "stream=codec_type",
    "-of",
    "csv=p=0",
)
_AUDIO_STREAM_LINE = b"audio"
_AUDIO_FILENAME_TEMPLATE = "audio{suffix}"
_MEDIA_INSPECTION_EVENT = "audio_media_inspection"


class MediaInspectionOutcome(StrEnum):
    """Structured outcomes recorded for the ffprobe inspection operation."""

    AUDIO_STREAM_FOUND = "audio_stream_found"
    PROBER_MISSING = "prober_missing"
    PROBER_START_FAILED = "prober_start_failed"
    INSPECTION_TIMED_OUT = "inspection_timed_out"
    PROCESS_FAILED = "process_failed"
    AUDIO_STREAM_MISSING = "audio_stream_missing"


class AudioSourceUnavailableError(RuntimeError):
    """The requested source could not be obtained as a readable file."""


class UnsupportedAudioMediaError(RuntimeError):
    """The obtained file has no audio stream or could not be inspected in time."""


class MediaProberUnavailableError(RuntimeError):
    """The required ffprobe executable is not installed or cannot be started."""


@dataclass(frozen=True)
class AudioSource:
    """Exactly one supplied audio URL or absolute local path."""

    url: str | None = None
    path: Path | None = None


async def transcribe_supplied_audio(source: AudioSource, language: str | None = None) -> str:
    """Obtain, inspect and transcribe supplied audio without retaining it."""
    if (source.url is None) == (source.path is None):
        raise ValueError(_SOURCE_EXCLUSIVE_ERROR)

    ffprobe = shutil.which(_FFPROBE_COMMAND)
    if ffprobe is None:
        logger.error(
            _MEDIA_INSPECTION_EVENT,
            outcome=MediaInspectionOutcome.PROBER_MISSING,
            command=_FFPROBE_COMMAND,
        )
        raise MediaProberUnavailableError(_FFPROBE_MISSING_ERROR)

    if source.path is not None:
        audio_path = _readable_audio_path(source.path)
        await _inspect_audio(ffprobe, audio_path)
        return await _transcribe(audio_path, language)

    assert source.url is not None
    parsed_url = urlparse(source.url)
    if parsed_url.scheme not in {_HTTP_SCHEME, _HTTPS_SCHEME}:
        raise AudioSourceUnavailableError(_UNSUPPORTED_SCHEME_ERROR)

    temporary_directory = tempfile.TemporaryDirectory(prefix=_TEMP_DIR_PREFIX)
    try:
        audio_path = await _fetch_audio(source.url, parsed_url, Path(temporary_directory.name))
        await _inspect_audio(ffprobe, audio_path)
        return await _transcribe(audio_path, language)
    finally:
        try:
            temporary_directory.cleanup()
        except OSError as error:
            logger.error(_TEMPORARY_AUDIO_CLEANUP_FAILED_LOG, exc_info=error)
            raise AudioSourceUnavailableError(_TEMPORARY_AUDIO_CLEANUP_FAILED_REASON) from error


def _readable_audio_path(path: Path) -> Path:
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.R_OK):
        raise AudioSourceUnavailableError(_UNREADABLE_PATH_ERROR.format(path=path))
    return path


async def _fetch_audio(url: str, parsed_url: ParseResult, directory: Path) -> Path:
    suffix = Path(parsed_url.path).suffix
    target = directory / _AUDIO_FILENAME_TEMPLATE.format(suffix=suffix)

    async def download() -> Path:
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(_HTTP_TIMEOUT_S)) as client:
            async with client.stream(_GET_METHOD, url) as response:
                response.raise_for_status()
                if not suffix:
                    media_type = (
                        response.headers.get(_CONTENT_TYPE_HEADER, _EMPTY_TEXT)
                        .split(_HEADER_PARAMETER_SEPARATOR, maxsplit=1)[0]
                        .strip()
                    )
                    target_suffix = mimetypes.guess_extension(media_type, strict=False) or _EMPTY_SUFFIX
                    target_path = directory / _AUDIO_FILENAME_TEMPLATE.format(suffix=target_suffix)
                else:
                    target_path = target
                with target_path.open(_BINARY_WRITE_MODE) as audio_file:
                    async for chunk in response.aiter_bytes():
                        audio_file.write(chunk)
                return target_path

    try:
        audio_path = await asyncio.wait_for(download(), timeout=AUDIO_STT_FETCH_TIMEOUT_S)
    except httpx.HTTPStatusError as error:
        host = urlparse(url).hostname or _UNKNOWN_HOST
        logger.warning(_FETCH_FAILED_LOG, scheme=urlparse(url).scheme, host=host)
        raise AudioSourceUnavailableError(_HTTP_STATUS_REASON.format(status=error.response.status_code)) from error
    except (httpx.TimeoutException, TimeoutError) as error:
        host = urlparse(url).hostname or _UNKNOWN_HOST
        logger.warning(_FETCH_FAILED_LOG, scheme=urlparse(url).scheme, host=host)
        raise AudioSourceUnavailableError(_FETCH_TIMEOUT_REASON) from error
    except (httpx.HTTPError, OSError) as error:
        host = urlparse(url).hostname or _UNKNOWN_HOST
        logger.warning(_FETCH_FAILED_LOG, scheme=urlparse(url).scheme, host=host)
        reason = (
            _FETCH_TIMEOUT_REASON
            if isinstance(error, TimeoutError)
            else _FETCH_FAILED_REASON.format(error_type=error.__class__.__name__)
        )
        raise AudioSourceUnavailableError(reason) from error

    logger.debug(_FETCHED_LOG, scheme=urlparse(url).scheme, host=urlparse(url).hostname or _UNKNOWN_HOST)
    return audio_path


async def _inspect_audio(ffprobe: str, audio_path: Path) -> None:
    started_at = perf_counter()
    try:
        # ffprobe is the installed native media parser; Python has no equivalent stream decoder.
        process = await asyncio.create_subprocess_exec(
            ffprobe,
            *_FFPROBE_ARGS,
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        logger.error(
            _MEDIA_INSPECTION_EVENT,
            outcome=MediaInspectionOutcome.PROBER_START_FAILED,
            duration_ms=(perf_counter() - started_at) * 1000,
            error_type=error.__class__.__name__,
        )
        raise MediaProberUnavailableError(_MISSING_PROBER_START_ERROR) from error

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=AUDIO_STT_INSPECTION_TIMEOUT_S)
    except TimeoutError as error:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.communicate()
        logger.warning(
            _MEDIA_INSPECTION_EVENT,
            outcome=MediaInspectionOutcome.INSPECTION_TIMED_OUT,
            duration_ms=(perf_counter() - started_at) * 1000,
            timeout_s=AUDIO_STT_INSPECTION_TIMEOUT_S,
            exit_code=process.returncode,
        )
        raise UnsupportedAudioMediaError(
            _INSPECTION_TIMEOUT_ERROR.format(timeout=AUDIO_STT_INSPECTION_TIMEOUT_S)
        ) from error

    audio_stream_count = sum(line == _AUDIO_STREAM_LINE for line in stdout.splitlines())
    if process.returncode != 0:
        logger.warning(
            _MEDIA_INSPECTION_EVENT,
            outcome=MediaInspectionOutcome.PROCESS_FAILED,
            duration_ms=(perf_counter() - started_at) * 1000,
            exit_code=process.returncode,
            audio_stream_count=audio_stream_count,
        )
        raise UnsupportedAudioMediaError(_UNSUPPORTED_STREAM_ERROR)
    if audio_stream_count == 0:
        logger.warning(
            _MEDIA_INSPECTION_EVENT,
            outcome=MediaInspectionOutcome.AUDIO_STREAM_MISSING,
            duration_ms=(perf_counter() - started_at) * 1000,
            exit_code=process.returncode,
            audio_stream_count=audio_stream_count,
        )
        raise UnsupportedAudioMediaError(_UNSUPPORTED_STREAM_ERROR)
    logger.debug(
        _MEDIA_INSPECTION_EVENT,
        outcome=MediaInspectionOutcome.AUDIO_STREAM_FOUND,
        duration_ms=(perf_counter() - started_at) * 1000,
        exit_code=process.returncode,
        audio_stream_count=audio_stream_count,
    )


async def _transcribe(audio_path: Path, language: str | None) -> str:
    try:
        return await asyncio.wait_for(
            transcribe_voice(str(audio_path), language), timeout=VOICE_TRANSCRIPTION_TIMEOUT_S
        )
    except NoSTTServiceError:
        raise
    except (STTTranscriptionFailedError, TimeoutError) as error:
        if isinstance(error, TimeoutError):
            reason = _TRANSCRIPTION_TIMEOUT_ERROR.format(timeout=VOICE_TRANSCRIPTION_TIMEOUT_S)
        else:
            reason = str(error)
        raise STTTranscriptionFailedError(reason) from error

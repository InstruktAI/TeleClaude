"""Execute fixed comment operations and bounded reads through the installed real gh."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from http.client import HTTPException, parse_headers
from io import BytesIO
from pathlib import Path
from typing import TextIO

from teleclaude.github._comment_results import CommentResponse
from teleclaude.paths import BIN_DIR

_GH = "gh"
_PATH = "PATH"
_EMPTY_BYTES = b""
_BASE_ENVIRONMENT = frozenset({_PATH, "HOME", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR"})
_GH_ARGUMENTS = (
    "api",
    "--hostname",
    "github.com",
    "--include",
    "--header",
    "Accept: application/vnd.github+json",
    "--header",
    "Content-Type: application/json",
    "--header",
    "X-GitHub-Api-Version: 2026-03-10",
)
_SEND_TIMEOUT_SECONDS = 60.0
_HTTP_PREFIX = b"HTTP/"
_RETRY_AFTER = "Retry-After"
_RATE_REMAINING = "X-RateLimit-Remaining"
_RATE_RESET = "X-RateLimit-Reset"
_ZERO = "0"
_WRAPPER_DIRECTORY = Path("install/wrappers")
_METHOD_OPTION = "--method"
_INPUT_OPTIONS = ("--input", "-")


class CommentMethod(StrEnum):
    """Only the fixed issue-comment effects supported by the posting owner."""

    GET = "GET"
    POST = "POST"
    PATCH = "PATCH"
    PUT = "PUT"
    DELETE = "DELETE"


@dataclass(frozen=True)
class Response(CommentResponse):
    """Legacy binary response shape retained for the remaining, separately corrected callers."""


class SendCancelled(asyncio.CancelledError):
    """Retain recovered child output for the owning operation's stage-aware verification."""

    def __init__(self, response: Response) -> None:
        super().__init__()
        self.response = response


def launch_environment() -> dict[str, str]:
    """Keep only host basics; provider controls and loader/proxy overrides never pass through."""
    return {
        name: value
        for name, value in os.environ.items()  # guard: direct-env-read - child-process startup seam
        if name in _BASE_ENVIRONMENT
    }


def gh_binary(environment: Mapping[str, str]) -> Path | None:
    wrapper = (BIN_DIR / _GH).resolve()
    source_wrapper = (Path(__file__).resolve().parents[1] / _WRAPPER_DIRECTORY / _GH).resolve()
    for directory in environment.get(_PATH, os.defpath).split(os.pathsep):
        candidate = (Path(directory) / _GH).resolve()
        if candidate not in (wrapper, source_wrapper) and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _response(stdout: bytes) -> Response:
    """Translate gh's included response with the standard-library header parser, without raw diagnostics."""
    stream = BytesIO(stdout)
    line = stream.readline()
    try:
        status = int(line.split()[1]) if line.startswith(_HTTP_PREFIX) else None
    except (IndexError, ValueError):
        status = None
    if status is None or not 100 <= status <= 599:
        return Response(None)
    try:
        headers = parse_headers(stream)
    except HTTPException:
        return Response(status)
    delay = None
    if status in (403, 429):
        try:
            seconds = headers.get(_RETRY_AFTER)
            reset = headers.get(_RATE_RESET)
            if seconds is not None:
                delay = timedelta(seconds=max(0, int(seconds)))
            elif headers.get(_RATE_REMAINING) == _ZERO and reset is not None:
                delay = max(datetime.fromtimestamp(int(reset), UTC) - datetime.now(UTC), timedelta())
        except (OverflowError, OSError, ValueError):
            delay = None
    return Response(status, stream.read(), delay)


async def send(
    binary: Path,
    endpoint: str,
    payload: bytes | None,
    environment: Mapping[str, str],
    directory: str,
    *,
    method: CommentMethod = CommentMethod.POST,
) -> Response:
    # Real gh owns provider HTTP/auth behavior; subprocess execution preserves the adopted native client contract.
    launch = asyncio.create_task(
        asyncio.create_subprocess_exec(
            str(binary),
            *_GH_ARGUMENTS,
            _METHOD_OPTION,
            method.value,
            *(_INPUT_OPTIONS if payload is not None else ()),
            endpoint,
            cwd=directory,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    )
    try:
        process = await asyncio.shield(launch)
    except OSError:
        return Response(None, started=False)
    except asyncio.CancelledError:
        try:
            process = await launch
        except OSError:
            raise SendCancelled(Response(None, started=False)) from None
        try:
            recovered = _response(await _reap(process))
        except OSError:
            recovered = Response(None)
        raise SendCancelled(recovered) from None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=_SEND_TIMEOUT_SECONDS)
    except (TimeoutError, OSError):
        return _response(await _reap(process))
    except asyncio.CancelledError:
        try:
            recovered = _response(await _reap(process))
        except OSError:
            recovered = Response(None)
        raise SendCancelled(recovered) from None
    # A process exit code is neither acceptance evidence nor safe-retry permission.
    return _response(stdout)


async def _reap(process: asyncio.subprocess.Process) -> bytes:
    """Settle the actual child after timeout, failed I/O or cancellation, without retrying its request."""
    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        stdout, _ = await process.communicate()
        return stdout
    except OSError:
        await process.wait()
        return _EMPTY_BYTES


async def native_read_process(
    binary: Path,
    arguments: tuple[str, ...],
    directory: str,
    environment: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run only reconstructed read/help arguments; real gh owns provider reads and formatting."""
    process = await asyncio.create_subprocess_exec(
        str(binary),
        *arguments,
        cwd=directory,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
    )
    try:
        return await asyncio.wait_for(process.wait(), timeout=_SEND_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.CancelledError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise

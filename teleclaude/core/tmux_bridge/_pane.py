"""Tmux pane operations: capture, query, pipe, and process state."""

import asyncio
import os
import pwd
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.runtime.binaries import resolve_tmux_query_binary
from teleclaude.utils import strip_ansi_codes

from ._subprocess import (
    SUBPROCESS_TIMEOUT_QUICK,
    SubprocessTimeoutError,
    TmuxSnapshotMalformedError,
    TmuxUnavailableError,
    communicate_with_timeout,
    get_snapshot_semaphore,
    wait_with_timeout,
)

logger = get_logger(__name__)

# User's shell basename, computed once at import
# Used for shell readiness detection in is_process_running()/wait_for_shell_ready()
_SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
_TMUX_OPERATION_ERRORS = (OSError, ValueError, SubprocessTimeoutError)
_TMUX_DIAGNOSTIC_ERRORS = (OSError, ValueError, TypeError, psutil.Error, SubprocessTimeoutError)
_SNAPSHOT_MARKER = "__TELECLAUDE_PANE_SNAPSHOT_BOUNDARY_9f6d5e53__"
_OBSERVATION_MARKER = "__TELECLAUDE_PANE_OBSERVATION_BOUNDARY_4c1e7a92__"
_OBSERVATION_CURSOR_FORMAT = "#{cursor_flag} #{cursor_y} #{cursor_x}"
_OBSERVATION_DISPLAY_FORMAT = _OBSERVATION_MARKER + _OBSERVATION_CURSOR_FORMAT
_CURSOR_VISIBLE_FLAG = "1"
_CURSOR_FIELD_COUNT = 3
_OUTPUT_ENCODING = "utf-8"
_OUTPUT_DECODE_ERRORS = "replace"
_TMUX_OPERATION_LABEL = "tmux operation"
_TMUX_CAPTURE_PANE = "capture-pane"
_TMUX_DISPLAY_MESSAGE = "display-message"
_TMUX_COMMAND_SEPARATOR = ";"
_TMUX_TARGET_FLAG = "-t"
_TMUX_PRINT_FLAG = "-p"
_TMUX_SOCKET_FLAG = "-S"
_PANE_PID_FORMAT = "#{pane_pid}"
_SERVER_PANE_PROCESS_FORMAT = "#{session_name}\t#{pane_pid}\t#{pane_tty}"
_TMUX_LIST_PANES = "list-panes"
_TMUX_ALL_FLAG = "-a"
_TMUX_FORMAT_FLAG = "-F"
_FIELD_SEPARATOR = "\t"
_SERVER_PANE_PROCESS_ERROR = "Platform pane-process snapshot is unavailable"
_TMUX_ESCAPES_FLAG = "-e"
_OBSERVE_FAILED_LOG = "Failed to observe pane from session %s: returncode=%d, stderr=%s"
_OBSERVE_TIMEOUT_LOG = "Timeout observing pane from session %s: %s"
_OBSERVE_ERROR_LOG = "Exception observing pane from session %s: %s"
_SNAPSHOT_MARKER_MISSING = "tmux snapshot output missing required boundary marker (stdout_bytes={size})"
_TMUX_UNAVAILABLE_ERROR = "tmux binary unavailable for {session_name}: {error}"
_ROW_SEPARATOR = "\n"
DEFAULT_CAPTURE_LINES = 200
FALLBACK_CAPTURE_LINES = 40
# Rows of a pane shown to an agent as evidence of what the pane displays.
PANE_EVIDENCE_LINES = 40


class _MissingPaneDiagnostic(StrEnum):
    """tmux diagnostics that represent unavailable host-pane liveness."""

    TARGET_NOT_FOUND = "can't find"
    TARGET_ABSENT = "no such"
    SERVER_UNAVAILABLE = "no server running"


@dataclass(frozen=True)
class PaneSnapshot:
    """Required per-tick tmux polling state.

    Contract:
    - These fields are the required polling boundary.
    - Poller control flow must depend only on these fields.
    - Optional enrichment must not be added here unless it comes from the same
      tmux invocation and cannot poison the tick when unavailable.
    """

    session_exists: bool
    pane_dead: bool
    output_raw: str
    output_normalized: str


@dataclass(frozen=True)
class PaneCursor:
    """Zero-based screen position of the visible input cursor."""

    row: int
    column: int


@dataclass(frozen=True)
class PaneObservation:
    """The visible pane surface and its cursor, read in one tmux invocation.

    ``text`` holds one line per screen row, so ``cursor.row`` indexes its lines
    directly. ``cursor`` is ``None`` when the program hides its cursor or the
    capture produced nothing.
    """

    text: str
    cursor: PaneCursor | None


@dataclass(frozen=True)
class PaneProcessIdentity:
    """A server-observed pane root and terminal, independent of caller markers."""

    session_name: str
    pid: int
    tty: str


def _query_binary() -> str:
    """The tmux binary for a read that only queries the running server (tmux-pane-orchestration)."""
    return resolve_tmux_query_binary(config.computer.tmux_binary)


async def get_server_pane_processes(socket_path: Path) -> tuple[PaneProcessIdentity, ...] | None:
    """Read all pane roots from one explicitly selected platform server."""
    command = (
        config.computer.tmux_binary,
        _TMUX_SOCKET_FLAG,
        str(socket_path),
        _TMUX_LIST_PANES,
        _TMUX_ALL_FLAG,
        _TMUX_FORMAT_FLAG,
        _SERVER_PANE_PROCESS_FORMAT,
    )
    try:
        # tmux is the authoritative live pane source and has no project Python binding.
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(process, None, SUBPROCESS_TIMEOUT_QUICK, _TMUX_OPERATION_LABEL)
        if process.returncode != 0:
            logger.warning(_SERVER_PANE_PROCESS_ERROR)
            return None
        panes: list[PaneProcessIdentity] = []
        for line in stdout.decode(_OUTPUT_ENCODING).splitlines():
            fields = line.split(_FIELD_SEPARATOR)
            if len(fields) != 3 or not fields[0] or not fields[1].isdigit() or int(fields[1]) <= 0:
                logger.warning(_SERVER_PANE_PROCESS_ERROR)
                return None
            panes.append(PaneProcessIdentity(fields[0], int(fields[1]), fields[2]))
        return tuple(panes)
    except _TMUX_OPERATION_ERRORS:
        logger.warning(_SERVER_PANE_PROCESS_ERROR, exc_info=True)
        return None


def _normalize_pane_output(text: str) -> str:
    """Normalize pane text for generic tmux change detection."""
    stripped = strip_ansi_codes(text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in stripped.split("\n"))


def pane_evidence_tail(surface_text: str) -> str:
    """Return the last evidence rows of a captured surface as plain text.

    Escape sequences are stripped and trailing blank rows dropped, so the bound
    counts rows that show something.
    """
    rows = _normalize_pane_output(surface_text).rstrip().split(_ROW_SEPARATOR)
    return _ROW_SEPARATOR.join(rows[-PANE_EVIDENCE_LINES:])


async def get_pane_tty(session_name: str) -> str | None:
    """Get tty path for the tmux pane backing a session."""
    try:
        cmd = [_query_binary(), "display-message", "-p", "-t", session_name, "#{pane_tty}"]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
        if result.returncode != 0:
            logger.error(
                "Failed to get pane tty for session %s: %s",
                session_name,
                stderr.decode().strip(),
            )
            return None

        tty = stdout.decode().strip()
        if not tty or tty in {"?", "??"}:
            return None
        return tty
    except _TMUX_OPERATION_ERRORS as e:
        logger.error("Exception getting pane tty for %s: %s", session_name, e)
        return None


async def get_pane_pid(session_name: str, *, socket_path: Path | None = None) -> int | None:
    """Get shell PID for the tmux pane backing a session."""
    try:
        cmd = [config.computer.tmux_binary]
        if socket_path is not None:
            cmd.extend((_TMUX_SOCKET_FLAG, str(socket_path)))
        cmd.extend((_TMUX_DISPLAY_MESSAGE, _TMUX_PRINT_FLAG, _TMUX_TARGET_FLAG, session_name, _PANE_PID_FORMAT))
        # tmux owns live pane identity; the existing subprocess boundary queries its server.
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, _TMUX_OPERATION_LABEL)
        if result.returncode != 0:
            logger.error(
                "Failed to get pane PID for session %s: %s",
                session_name,
                stderr.decode().strip(),
            )
            return None

        pid_str = stdout.decode().strip()
        if not pid_str.isdigit():
            return None
        return int(pid_str)
    except _TMUX_OPERATION_ERRORS as e:
        logger.error("Exception getting pane PID for %s: %s", session_name, e)
        return None


async def get_pane_process_tree(session_name: str) -> list[psutil.Process] | None:
    """Collect the pane process and its descendants.

    Returns ``None`` when the pane pid cannot be resolved — the capture
    failed and nothing is known about the tree. Returns ``[]`` only when the
    pane genuinely hosts no live process. These two states must never
    collapse: a capture failure is not the same as an empty tree.
    """
    pane_pid = await get_pane_pid(session_name)
    if pane_pid is None:
        return None

    def _collect() -> list[psutil.Process]:
        root = psutil.Process(pane_pid)
        return [root, *root.children(recursive=True)]

    try:
        return await asyncio.to_thread(_collect)
    except psutil.NoSuchProcess:
        return []
    except psutil.Error as e:
        logger.warning("Failed to collect pane process tree for %s: %s", session_name, e)
        return None


async def wait_for_processes_exit(procs: list[psutil.Process], timeout: float) -> list[psutil.Process]:
    """Wait up to timeout seconds for procs to exit; return processes still alive."""

    def _wait() -> list[psutil.Process]:
        alive: list[psutil.Process]
        _, alive = psutil.wait_procs(procs, timeout=timeout)
        return alive

    return await asyncio.to_thread(_wait)


async def capture_pane(
    session_name: str,
    *,
    capture_lines: int | None = None,
) -> str:
    """Capture pane output from tmux session.

    Args:
        session_name: Session name

    Returns:
        Captured output as string
    """
    try:
        # -p = print to stdout
        # -S -N = capture from the last N lines of scrollback.
        # -J = preserve trailing spaces (better for capturing exact output)
        # -e = include escape sequences (ANSI codes for styling detection)
        window_lines = capture_lines if isinstance(capture_lines, int) and capture_lines > 0 else DEFAULT_CAPTURE_LINES
        cmd = [
            _query_binary(),
            "capture-pane",
            "-t",
            session_name,
            "-p",
            "-J",
            "-e",
            "-S",
            f"-{window_lines}",
        ]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            return stdout.decode("utf-8", errors="replace")

        logger.warning(
            "Failed to capture pane from session %s: returncode=%d, stderr=%s",
            session_name,
            result.returncode,
            stderr.decode().strip(),
        )
        return ""

    except SubprocessTimeoutError as e:
        logger.error("Timeout capturing pane from session %s: %s", session_name, e)
        raise
    except (OSError, ValueError) as e:
        logger.error("Exception capturing pane from session %s: %s", session_name, e)
        raise


async def observe_visible_pane(session_name: str) -> PaneObservation | None:
    """Capture the visible pane surface together with its cursor state.

    Both facts come from one tmux invocation, so the text and the cursor
    describe the same moment. Wrapped lines are not joined: every screen row is
    one line of the returned text. A capture that failed returns ``None``: no
    surface was seen, which is not the same as a surface showing nothing.
    """
    cmd = [
        config.computer.tmux_binary,
        _TMUX_CAPTURE_PANE,
        _TMUX_TARGET_FLAG,
        session_name,
        _TMUX_PRINT_FLAG,
        _TMUX_ESCAPES_FLAG,
        _TMUX_COMMAND_SEPARATOR,
        _TMUX_DISPLAY_MESSAGE,
        _TMUX_TARGET_FLAG,
        session_name,
        _TMUX_PRINT_FLAG,
        _OBSERVATION_DISPLAY_FORMAT,
    ]
    try:
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, _TMUX_OPERATION_LABEL)

        if result.returncode != 0:
            logger.warning(_OBSERVE_FAILED_LOG, session_name, result.returncode, stderr.decode().strip())
            return None

        return _parse_observation_stdout(stdout)

    except SubprocessTimeoutError as e:
        logger.error(_OBSERVE_TIMEOUT_LOG, session_name, e)
        raise
    except (OSError, ValueError) as e:
        logger.error(_OBSERVE_ERROR_LOG, session_name, e)
        raise


def _parse_observation_stdout(stdout: bytes) -> PaneObservation:
    """Split one tmux call's surface text from its trailing cursor state."""
    decoded = stdout.decode(_OUTPUT_ENCODING, errors=_OUTPUT_DECODE_ERRORS)
    if _OBSERVATION_MARKER not in decoded:
        raise TmuxSnapshotMalformedError(_SNAPSHOT_MARKER_MISSING.format(size=len(stdout)))

    text, cursor_text = decoded.rsplit(_OBSERVATION_MARKER, 1)
    fields = cursor_text.split()
    if len(fields) != _CURSOR_FIELD_COUNT or fields[0] != _CURSOR_VISIBLE_FLAG:
        return PaneObservation(text=text, cursor=None)
    row_text, column_text = fields[1:]
    if not row_text.isdigit() or not column_text.isdigit():
        return PaneObservation(text=text, cursor=None)
    return PaneObservation(text=text, cursor=PaneCursor(row=int(row_text), column=int(column_text)))


def _parse_snapshot_stdout(stdout: bytes) -> tuple[str, bool]:
    """Parse combined capture-pane/list-panes output from a single tmux call."""
    decoded = stdout.decode("utf-8", errors="replace")
    if _SNAPSHOT_MARKER not in decoded:
        raise TmuxSnapshotMalformedError(_SNAPSHOT_MARKER_MISSING.format(size=len(stdout)))

    output_text, pane_state_text = decoded.rsplit(_SNAPSHOT_MARKER, 1)
    lines = pane_state_text.strip().splitlines()
    panes = [line.strip() for line in lines if line.strip()]
    pane_dead = bool(panes) and all(int(pane) == 1 for pane in panes if pane.isdigit())
    return output_text, pane_dead


async def collect_pane_snapshot(session_name: str, *, capture_lines: int | None = None) -> PaneSnapshot:
    """Collect required polling state for one session through the tick's shared snapshot call.

    This is the hot polling boundary. The snapshot must remain narrow and
    stable: liveness plus pane output only. Requests arriving within one batch
    window share a single tmux subprocess (output-polling, one snapshot call per tick).
    """
    window_lines = capture_lines if isinstance(capture_lines, int) and capture_lines > 0 else DEFAULT_CAPTURE_LINES
    return await _snapshot_batcher().request(session_name, window_lines)


# How long the first request of a tick waits for the others before the shared call runs.
_SNAPSHOT_BATCH_WINDOW_S = 0.05
_BATCH_MARKER = "__TELECLAUDE_PANE_BATCH_SESSION_3b8e1d64__"


class _SnapshotBatcher:
    """Gather the snapshot requests of one tick and take them in one chained tmux call."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._pending: dict[str, tuple[int, list[asyncio.Future[PaneSnapshot]]]] = {}
        self._scheduled = False

    async def request(self, session_name: str, window_lines: int) -> PaneSnapshot:
        future: asyncio.Future[PaneSnapshot] = self._loop.create_future()
        lines, waiters = self._pending.get(session_name, (window_lines, []))
        waiters.append(future)
        self._pending[session_name] = (max(lines, window_lines), waiters)
        if not self._scheduled:
            self._scheduled = True
            self._loop.call_later(_SNAPSHOT_BATCH_WINDOW_S, self._start_flush)
        return await future

    def _start_flush(self) -> None:
        self._scheduled = False
        batch, self._pending = self._pending, {}
        if batch:
            self._loop.create_task(self._flush(batch))

    async def _flush(self, batch: dict[str, tuple[int, list[asyncio.Future[PaneSnapshot]]]]) -> None:
        remaining = list(batch)
        try:
            while remaining:
                results, failed = await _run_snapshot_chain([(name, batch[name][0]) for name in remaining])
                for name, snapshot in results.items():
                    _resolve(batch[name][1], snapshot)
                if failed is None:
                    break
                _resolve(batch[failed][1], _MISSING_SNAPSHOT)
                remaining = remaining[remaining.index(failed) + 1 :]
        except BaseException as error:  # every waiter of the batch learns the failure that ended it
            for name in remaining:
                for waiter in batch[name][1]:
                    if not waiter.done():
                        waiter.set_exception(error)
            if not isinstance(error, Exception):
                raise


_batchers: dict[asyncio.AbstractEventLoop, _SnapshotBatcher] = {}


def _snapshot_batcher() -> _SnapshotBatcher:
    """The running loop's batcher; futures and the batch task belong to that loop."""
    loop = asyncio.get_running_loop()
    batcher = _batchers.get(loop)
    if batcher is None:
        batcher = _batchers[loop] = _SnapshotBatcher(loop)
    return batcher


def _resolve(waiters: list[asyncio.Future[PaneSnapshot]], snapshot: PaneSnapshot) -> None:
    for waiter in waiters:
        if not waiter.done():
            waiter.set_result(snapshot)


_MISSING_SNAPSHOT = PaneSnapshot(session_exists=False, pane_dead=False, output_raw="", output_normalized="")


async def _run_snapshot_chain(targets: list[tuple[str, int]]) -> tuple[dict[str, PaneSnapshot], str | None]:
    """Snapshot ``targets`` in one tmux call; also name the session whose missing pane ended the chain, if any.

    tmux stops a command chain at its first failing command, so a session the server no longer
    holds ends the chain at its own capture: the sessions before it are complete, the ones after it
    were not attempted.
    """
    cmd: list[str] = [_query_binary()]
    for index, (session_name, window_lines) in enumerate(targets):
        if index:
            cmd.append(";")
        cmd += [
            "display-message", "-p", _BATCH_MARKER + session_name, ";",
            "capture-pane", "-t", session_name, "-p", "-J", "-e", "-S", f"-{window_lines}", ";",
            "display-message", "-p", _SNAPSHOT_MARKER, ";",
            "list-panes", "-t", session_name, "-F", "#{pane_dead}",
        ]  # fmt: skip
    first = targets[0][0]
    # The slot encloses spawn and communicate so the timeout budget starts at
    # spawn, never while a requester waits for a free slot.
    async with get_snapshot_semaphore():
        try:
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as e:
            raise TmuxUnavailableError(_TMUX_UNAVAILABLE_ERROR.format(session_name=first, error=e)) from e
        # A timeout here (SubprocessTimeoutError) is logged (throttled/aggregated) by the poll
        # loop that owns retry cadence, not per tick here.
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
    stderr_text = stderr.decode().strip()
    if result.returncode == 127:
        # Logged (throttled/aggregated) by the poll loop that owns retry cadence, not per tick here.
        raise TmuxUnavailableError(_TMUX_UNAVAILABLE_ERROR.format(session_name=first, error=stderr_text))
    segments = _split_batch_stdout(stdout)
    results: dict[str, PaneSnapshot] = {}
    failed: str | None = None
    for session_name, _lines in targets:
        segment = segments.get(session_name)
        if segment is None or (result.returncode != 0 and session_name == _last_started(segments)):
            failed = session_name
            break
        output_text, pane_dead = _parse_snapshot_stdout(segment)
        results[session_name] = PaneSnapshot(
            session_exists=True,
            pane_dead=pane_dead,
            output_raw=output_text,
            output_normalized=_normalize_pane_output(output_text),
        )
    if failed is not None and not any(d in stderr_text.lower() for d in _MissingPaneDiagnostic):
        logger.warning(
            "Failed to collect pane snapshot for session %s: returncode=%d, stderr=%s",
            failed,
            result.returncode,
            stderr_text,
        )
        raise ValueError(f"tmux snapshot failed for {failed}: {stderr_text}")
    return results, failed


def _split_batch_stdout(stdout: bytes) -> dict[str, bytes]:
    """Each session's part of a batched snapshot, in chain order, keyed by session name."""
    decoded = stdout.decode("utf-8", errors="replace")
    segments: dict[str, bytes] = {}
    for part in decoded.split(_BATCH_MARKER)[1:]:
        name, _, body = part.partition("\n")
        segments[name] = body.encode("utf-8")
    return segments


def _last_started(segments: dict[str, bytes]) -> str | None:
    return next(reversed(segments), None)


async def kill_session(session_name: str) -> bool:
    """Kill a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "kill-session", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except _TMUX_OPERATION_ERRORS as e:
        print(f"Error killing session: {e}")
        return False


async def list_tmux_sessions() -> list[str]:
    """List all tmux sessions.

    Returns:
        List of session names
    """
    try:
        cmd = [_query_binary(), "list-sessions", "-F", "#{session_name}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            sessions: list[str] = stdout.decode("utf-8").strip().split("\n")
            return [s for s in sessions if s]  # Filter empty strings
        return []

    except _TMUX_OPERATION_ERRORS as e:
        print(f"Error listing sessions: {e}")
        return []


async def session_exists(session_name: str, log_missing: bool = True) -> bool:
    """Check if a tmux session exists.

    Args:
        session_name: Session name
        log_missing: If True, log ERROR with diagnostics when session is missing.
                     Set to False when checking expected-terminated sessions to avoid noise.

    Returns:
        True if session exists, False otherwise
    """
    try:
        cmd = [_query_binary(), "has-session", "-t", session_name]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            if log_missing:
                # Session died - capture system state for diagnostics
                try:
                    # Get all tmux sessions
                    tmux_list_result = await asyncio.create_subprocess_exec(
                        config.computer.tmux_binary,
                        "list-sessions",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    tmux_list_stdout, _ = await communicate_with_timeout(
                        tmux_list_result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation"
                    )
                    tmux_sessions = tmux_list_stdout.decode().strip().split("\n") if tmux_list_stdout else []

                    # Get tmux processes and system metrics off the event loop to avoid blocking
                    def _collect_psutil_diag() -> tuple[list[object], object, object]:
                        procs: list[object] = [
                            {"pid": p.pid, "create_time": p.create_time()}
                            for p in psutil.process_iter(["pid", "name", "create_time"])
                            if Path(config.computer.tmux_binary).name.lower() in (p.info.get("name") or "").lower()
                        ]
                        mem = psutil.virtual_memory()
                        cpu = psutil.cpu_percent(interval=0.1)
                        return procs, mem, cpu

                    tmux_processes, memory, cpu_percent = await asyncio.to_thread(_collect_psutil_diag)

                    logger.error(
                        "Session %s does not exist (died unexpectedly)",
                        session_name,
                        extra={
                            "session_name": session_name,
                            "stderr": stderr.decode().strip(),
                            "tmux_sessions_count": len([s for s in tmux_sessions if s]),
                            "tmux_processes_count": len(tmux_processes),
                            "system_memory_used_mb": memory.used // 1024 // 1024,  # type: ignore
                            "system_memory_percent": memory.percent,  # type: ignore
                            "system_cpu_percent": cpu_percent,
                        },
                    )
                except _TMUX_DIAGNOSTIC_ERRORS as diag_error:
                    logger.warning("Failed to capture diagnostics: %s", diag_error)

        return result.returncode == 0

    except SubprocessTimeoutError as e:
        logger.error("Timeout in session_exists for %s: %s", session_name, e)
        raise
    except (OSError, ValueError) as e:
        logger.error("Exception in session_exists for %s: %s", session_name, e)
        raise


async def get_current_command(session_name: str) -> str | None:
    """Get the current foreground command running in a tmux pane.

    Uses tmux's #{pane_current_command} variable to detect interactive apps.

    Args:
        session_name: Session name

    Returns:
        Command name (e.g., "zsh", "claude", "vim") or None if detection failed
    """
    try:
        cmd = [config.computer.tmux_binary, "display-message", "-p", "-t", session_name, "#{pane_current_command}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            logger.warning(
                "Failed to get current command for %s: returncode=%d, stderr=%s",
                session_name,
                result.returncode,
                stderr.decode().strip(),
            )
            return None

        command: str = stdout.decode().strip()
        return command

    except _TMUX_OPERATION_ERRORS as e:
        logger.error("Exception in get_current_command for %s: %s", session_name, e)
        return None


async def wait_for_shell_ready(
    session_name: str,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.2,
) -> bool:
    """Wait until the tmux pane returns to the user's shell.

    Returns True when the shell is in the foreground, False on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        current = await get_current_command(session_name)
        if current and current.lower() == _SHELL_NAME:
            return True
        await asyncio.sleep(poll_interval_s)
    return False


async def is_process_running(session_name: str) -> bool:
    """Return True if tmux foreground command is not the user's shell."""
    current = await get_current_command(session_name)
    if not current:
        return False
    return current.lower() != _SHELL_NAME


async def is_pane_dead(session_name: str) -> bool:
    """Return True if all tmux panes are marked dead (shell exited)."""
    try:
        cmd = [config.computer.tmux_binary, "list-panes", "-t", session_name, "-F", "#{pane_dead}"]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
        if result.returncode != 0:
            return False
        lines = stdout.decode("utf-8").strip().split("\n") if stdout else []
        panes = [line.strip() for line in lines if line.strip()]
        if not panes:
            return False
        return all(int(pane) == 1 for pane in panes if pane.isdigit())
    except SubprocessTimeoutError as e:
        logger.error("Timeout checking pane_dead for %s: %s", session_name, e)
        raise
    except (OSError, ValueError) as e:
        logger.error("Exception checking pane_dead for %s: %s", session_name, e)
        raise


async def get_session_pane_id(session_name: str) -> str | None:
    """Get the pane ID for a session (for pipe-pane).

    Args:
        session_name: Session name

    Returns:
        Pane ID or None
    """
    try:
        cmd = [config.computer.tmux_binary, "list-panes", "-t", session_name, "-F", "#{pane_id}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            pane_id: str = stdout.decode("utf-8").strip()
            return pane_id if pane_id else None
        return None

    except _TMUX_OPERATION_ERRORS as e:
        print(f"Error getting pane ID: {e}")
        return None


async def start_pipe_pane(session_name: str, command: str) -> bool:
    """Start piping pane output to a command.

    Args:
        session_name: Session name
        command: Command to pipe output to

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "pipe-pane", "-t", session_name, "-o", command]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except _TMUX_OPERATION_ERRORS as e:
        print(f"Error starting pipe-pane: {e}")
        return False


async def stop_pipe_pane(session_name: str) -> bool:
    """Stop piping pane output.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "pipe-pane", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except _TMUX_OPERATION_ERRORS as e:
        print(f"Error stopping pipe-pane: {e}")
        return False


async def get_pane_title(session_name: str) -> str | None:
    """Get the pane title for a tmux session.

    Args:
        session_name: Session name

    Returns:
        Pane title string or None if failed
    """
    try:
        cmd = [config.computer.tmux_binary, "display-message", "-p", "-t", session_name, "#{pane_title}"]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            pane_title: str = stdout.decode().strip()
            return pane_title

        return None

    except _TMUX_OPERATION_ERRORS as e:
        logger.error("Failed to get pane title for %s: %s", session_name, e)
        return None

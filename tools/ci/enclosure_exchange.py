"""One privileged child exchanges phase evidence with its original observing parent over native pipes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import select
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_actions import NativeMutation, dispatch_action
from tools.ci.enclosure_admission import ACTUAL_SOURCE_ROOT, ENTRY
from tools.ci.enclosure_contract import (
    Action,
    AdmittedDeadline,
    Cutoff,
    JsonObject,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_guest import Role, close_evidence_descriptors
from tools.ci.enclosure_journal import CLOSURE_ACTIONS, ActionResult, Controller, Outcome
from tools.ci.enclosure_journal import Key as JournalKey
from tools.ci.enclosure_owner import MANIFEST_NAME, RunOwner
from tools.ci.enclosure_privileged import OUTSIDE_ENVIRONMENT, PrivilegedAction

REQUEST_ENVIRONMENT: Final = "TC_RA_PRIVILEGED_REQUEST"
PYTHON: Final = "/usr/bin/python3.12"
ROLE_OPTION: Final = "--enclosure-role"
MANIFEST_OPTION: Final = "--enclosure-manifest"
ACTION_OPTION: Final = "--enclosure-action"
ISOLATED: Final = "-I"
NO_SITE: Final = "-S"
STDERR_FILE: Final = "helper-{action}.stderr"
UTF8: Final = "utf-8"
NEWLINE: Final = b"\n"
FRAME_LIMIT: Final = 1024 * 1024
READ_BYTES: Final = 4096
NANOSECONDS: Final = 1_000_000_000
JSON_SEPARATORS: Final = (",", ":")
ERROR_EXCHANGE: Final = "the original privileged helper exchange is missing, malformed, late or inconsistent"
ERROR_UNKNOWN: Final = "privileged helper startup or outcome remains unknown; retain the original startup handle and do not repeat {action}"
ERROR_EXIT: Final = "privileged helper {action} exited {status} after its durable effect receipt; retain both outcomes"


class Key(StrEnum):
    """Private pipe fields; no review decision or authority is inferred from their text."""

    DIRECTORY_FD = "directory_fd"
    MANIFEST_DIGEST = "manifest_digest"
    MAXIMUM_SECONDS = "maximum_seconds"
    QUALIFICATION_VECTOR = "qualification_vector"
    BINDING = "binding"
    MUTATION = "mutation"
    RESULT = "result"
    ACTION = "action"
    STARTUP_STATE = "startup_state"
    ERROR_CLASS = "error_class"
    PID = "pid"
    START_TICKS = "start_ticks"
    UID = "uid"
    BOOT_ID = "boot_id"
    EXIT_STATUS = "exit_status"


class StartupState(StrEnum):
    """Observed task state, never physical closure or permission to replace its original process."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HelperUncertain(RuntimeError):
    """Keep the original startup task and its eventual native result available to bounded closure."""

    def __init__(self, startup: HelperStartup, action: Action) -> None:
        super().__init__(ERROR_UNKNOWN.format(action=action))
        self.startup = startup
        self.action = action

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        """Expose a native handle only after creation returned it, including a later local descriptor-close error."""
        return self.startup.process


class HelperExitFailed(RuntimeError):
    """A known effect receipt and a separately known unsuccessful helper exit; neither fact erases the other."""

    def __init__(self, startup: HelperStartup, receipt: ActionResult, exit_status: int) -> None:
        super().__init__(ERROR_EXIT.format(action=startup.action, status=exit_status))
        self.startup = startup
        self.receipt = receipt
        self.exit_status = exit_status


def _encode(value: JsonObject) -> bytes:
    data = json.dumps(value, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False).encode(UTF8) + NEWLINE
    if len(data) > FRAME_LIMIT:
        raise ValueError(ERROR_EXCHANGE)
    return data


def _remaining(end_ns: int) -> float:
    remaining = (end_ns - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(ERROR_EXCHANGE)
    return remaining


def _write_frame(value: JsonObject, end_ns: int) -> None:
    data = _encode(value)
    os.set_blocking(1, False)
    while data:
        _, ready, _ = select.select([], [1], [], _remaining(end_ns))
        if not ready:
            raise TimeoutError(ERROR_EXCHANGE)
        written = os.write(1, data)
        if written <= 0:
            raise OSError(ERROR_EXCHANGE)
        data = data[written:]
    _remaining(end_ns)


def _read_frame(end_ns: int) -> JsonObject:
    data = bytearray()
    os.set_blocking(0, False)
    while not data.endswith(NEWLINE):
        ready, _, _ = select.select([0], [], [], _remaining(end_ns))
        if not ready:
            raise TimeoutError(ERROR_EXCHANGE)
        part = os.read(0, min(READ_BYTES, FRAME_LIMIT + 1 - len(data)))
        if not part or len(data) + len(part) > FRAME_LIMIT:
            raise ValueError(ERROR_EXCHANGE)
        data.extend(part)
    if NEWLINE in data[:-1]:
        raise ValueError(ERROR_EXCHANGE)
    _remaining(end_ns)
    return parse_object(bytes(data))


def _result(record: JsonObject, action: Action) -> ActionResult:
    if (
        set(record) != {JournalKey.ACTION, JournalKey.STATUS, JournalKey.EVIDENCE}
        or record[JournalKey.ACTION] != action
    ):
        raise ValueError(ERROR_EXCHANGE)
    return ActionResult(Outcome(text(record, JournalKey.STATUS)), object_value(record[JournalKey.EVIDENCE]))


def run_helper(manifest: Path, action: Action) -> ActionResult:
    """Use the inherited ownership descriptor; ask the original parent while the helper holds its journal lock."""
    request = parse_object(os.environ[REQUEST_ENVIRONMENT].encode(UTF8))
    deadline = AdmittedDeadline.from_record(request, require_vector=False)
    vector = request[Key.QUALIFICATION_VECTOR]
    if vector is not None and not isinstance(vector, str):
        raise ValueError(ERROR_EXCHANGE)
    context = PrivilegedAction.load(
        manifest,
        text(request, Key.MANIFEST_DIGEST),
        positive_integer(request, Key.DIRECTORY_FD),
        action,
        deadline,
        positive_integer(request, Key.MAXIMUM_SECONDS),
        vector,
    )
    try:

        def observe(mutation: NativeMutation, end_ns: int) -> ActionResult:
            native: JsonObject = {
                JournalKey.ACTION: mutation.action.value,
                JournalKey.EVIDENCE: dict(mutation.evidence),
            }
            _write_frame(
                {Key.BINDING: context.owner.journal.owner_record, Key.MUTATION: native, Cutoff.COMMAND_END_NS: end_ns},
                end_ns,
            )
            reply = _read_frame(end_ns)
            if set(reply) != {Key.RESULT}:
                raise ValueError(ERROR_EXCHANGE)
            return _result(object_value(reply[Key.RESULT]), action)

        result = dispatch_action(context, observe)
        # The durable outcome exists before this acknowledgment; losing this line cannot authorize a repeat.
        _write_frame({Key.RESULT: result.record(action)}, deadline.effective_end())
        return result
    finally:
        context.close()


async def _line(reader: asyncio.StreamReader, end_ns: int) -> JsonObject:
    async with asyncio.timeout(_remaining(end_ns)):
        data = await reader.readline()
    if not data:
        raise EOFError(ERROR_EXCHANGE)
    if len(data) > FRAME_LIMIT or not data.endswith(NEWLINE):
        raise ValueError(ERROR_EXCHANGE)
    return parse_object(data)


class HelperStartup:
    """One retained native startup; caller cancellation never cancels its transport construction."""

    def __init__(self, owner: RunOwner, action: Action, request: JsonObject, end_ns: int) -> None:
        self.action = action
        self.command_end_ns = end_ns
        self.process: asyncio.subprocess.Process | None = None
        self.identity: Controller | None = None
        self.task = asyncio.create_task(self._start(owner, action, request, end_ns))

    def record(self) -> JsonObject:
        """Read the original native handles only; absent startup identity or exit remains explicitly absent."""
        error: BaseException | None = None
        if self.task.cancelled():
            state = StartupState.CANCELLED
        elif not self.task.done():
            state = StartupState.PENDING
        else:
            error = self.task.exception()
            state = StartupState.FAILED if error is not None else StartupState.READY
        identity = self.identity
        return {
            Key.ACTION: self.action.value,
            Cutoff.COMMAND_END_NS: self.command_end_ns,
            Key.STARTUP_STATE: state.value,
            Key.ERROR_CLASS: type(error).__name__ if error is not None else None,
            Key.PID: self.process.pid if self.process is not None else None,
            Key.START_TICKS: identity.start_ticks if identity is not None else None,
            Key.UID: identity.uid if identity is not None else None,
            Key.BOOT_ID: identity.boot_id if identity is not None else None,
            Key.EXIT_STATUS: self.process.returncode if self.process is not None else None,
        }

    def abandon_input(self) -> None:
        """Close only the eventual input pipe, without cancelling startup or closing the process transport."""
        self.task.add_done_callback(self._close_input)

    def _close_input(self, task: asyncio.Task[asyncio.subprocess.Process]) -> None:
        if not task.cancelled():
            task.exception()  # Retrieve native startup errors; the original task retains them for closure.
        if self.process is not None and self.process.stdin is not None:
            self.process.stdin.close()

    async def _start(
        self, owner: RunOwner, action: Action, request: JsonObject, end_ns: int
    ) -> asyncio.subprocess.Process:
        # The uncancelled startup task owns this descriptor until native creation resolves, including late completion.
        _remaining(end_ns)
        stderr = os.open(
            STDERR_FILE.format(action=action),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=owner.journal.directory_fd,
        )
        try:
            _remaining(end_ns)
            self.process = await asyncio.create_subprocess_exec(
                PYTHON,
                ISOLATED,
                NO_SITE,
                str(ACTUAL_SOURCE_ROOT / ENTRY),
                ROLE_OPTION,
                Role.PRIVILEGED.value,
                MANIFEST_OPTION,
                str(owner.directory / MANIFEST_NAME),
                ACTION_OPTION,
                action.value,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                limit=FRAME_LIMIT,
                pass_fds=(owner.journal.directory_fd,),
                cwd=ACTUAL_SOURCE_ROOT,
                env={**OUTSIDE_ENVIRONMENT, REQUEST_ENVIRONMENT: _encode(request).decode(UTF8)},
                umask=0o077,
            )
            self.identity = Controller.capture(self.process.pid)
            if self.identity.uid != 0 or self.identity.boot_id != owner.journal.binding.controller.boot_id:
                raise ValueError(ERROR_EXCHANGE)
            return self.process
        finally:
            close_evidence_descriptors(stderr)


async def run_privileged(
    owner: RunOwner,
    action: Action,
    deadline: AdmittedDeadline,
    maximum_seconds: int,
    qualification_vector: str | None,
    observe: Callable[[NativeMutation, int, HelperStartup], Awaitable[ActionResult]],
    startups: list[HelperStartup],
) -> ActionResult:
    """Keep original observations running during one child; read its journal only after positive child exit."""
    owner.journal.binding.controller.require_alive()
    if deadline.outer_end_ns != owner.journal.deadline.end_ns:
        raise ValueError(ERROR_EXCHANGE)
    reserve = 0 if action in CLOSURE_ACTIONS else owner.journal.deadline.reserve_ns
    end_ns = min(deadline.command_end(maximum_seconds), owner.journal.deadline.end_ns - reserve)
    deadline = AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns)
    _remaining(end_ns)
    request: JsonObject = {
        Key.DIRECTORY_FD: owner.journal.directory_fd,
        Key.MANIFEST_DIGEST: hashlib.sha256(owner.manifest_bytes).hexdigest(),
        Key.MAXIMUM_SECONDS: maximum_seconds,
        Key.QUALIFICATION_VECTOR: qualification_vector,
        Cutoff.OUTER_END_NS: deadline.outer_end_ns,
        Cutoff.VECTOR_END_NS: deadline.vector_end_ns,
        Cutoff.COMMAND_END_NS: deadline.command_end_ns,
    }
    startup = HelperStartup(owner, action, request, end_ns)
    startups.append(startup)
    try:
        async with asyncio.timeout(_remaining(end_ns)):
            process = await asyncio.shield(startup.task)
        _remaining(end_ns)
    except BaseException as error:
        startup.abandon_input()
        raise HelperUncertain(startup, action) from error
    reader, writer = process.stdout, process.stdin
    if reader is None or writer is None:
        startup.abandon_input()
        raise HelperUncertain(startup, action)
    final: ActionResult | None = None
    try:
        async with asyncio.timeout(_remaining(end_ns)):
            phase = await _line(reader, end_ns)
            if (
                set(phase) != {Key.BINDING, Key.MUTATION, Cutoff.COMMAND_END_NS}
                or phase[Key.BINDING] != owner.journal.owner_record
            ):
                raise ValueError(ERROR_EXCHANGE)
            phase_end = positive_integer(phase, Cutoff.COMMAND_END_NS)
            if phase_end > end_ns:
                raise ValueError(ERROR_EXCHANGE)
            _remaining(phase_end)
            native = object_value(phase[Key.MUTATION])
            if set(native) != {JournalKey.ACTION, JournalKey.EVIDENCE} or native[JournalKey.ACTION] != action:
                raise ValueError(ERROR_EXCHANGE)
            result = await observe(
                NativeMutation(action, object_value(native[JournalKey.EVIDENCE])), phase_end, startup
            )
            _remaining(phase_end)
            writer.write(_encode({Key.RESULT: result.record(action)}))
            await writer.drain()
            writer.close()
            try:
                terminal = await _line(reader, end_ns)
            except EOFError:
                pass
            else:
                if set(terminal) != {Key.RESULT}:
                    raise ValueError(ERROR_EXCHANGE)
                final = _result(object_value(terminal[Key.RESULT]), action)
                if await reader.read(1):
                    raise ValueError(ERROR_EXCHANGE)
            exit_status = await process.wait()
        # The helper released its flock and exited. This single read also recovers a lost final acknowledgment.
        receipt = owner.journal.receipt(action)
        if receipt is None or (final is not None and receipt != final):
            raise ValueError(ERROR_EXCHANGE)
        if receipt.status is Outcome.SUCCEEDED and exit_status != 0:
            raise HelperExitFailed(startup, receipt, exit_status)
        return receipt
    except HelperExitFailed:
        raise
    except BaseException as error:
        raise HelperUncertain(startup, action) from error
    finally:
        writer.close()

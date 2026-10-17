"""Concrete outside native command receipts for the closed privileged action producers."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_admission import ACTUAL_SOURCE_ROOT, ActionAdmission, SourceAdmission
from tools.ci.enclosure_contract import Action, AdmittedDeadline, Cutoff, parse_object
from tools.ci.enclosure_data import PROVISION_ENVIRONMENT
from tools.ci.enclosure_guest import Record, Role, _append, _output, close_evidence_descriptors
from tools.ci.enclosure_guest_manifest import read_guest_input
from tools.ci.enclosure_journal import ActionResult
from tools.ci.enclosure_native import NativeRead, execute_native, read_native_stdout
from tools.ci.enclosure_owner import PARENT_DESCRIPTOR, HelperOwner

COMMAND_JOURNAL: Final = "commands-{action}.jsonl"
COMMAND_STDOUT: Final = "commands-{action}-{sequence}.stdout"
COMMAND_STDERR: Final = "commands-{action}-{sequence}.stderr"
ERROR_DEADLINE: Final = "outside native command exhausted its original command/vector/outer allowance"
ERROR_DUPLICATE: Final = (
    "this privileged action already has a native command journal; no repeated invocation is admitted"
)
ERROR_JOURNAL: Final = "preserving outside native command uncertainty also failed: {error_class}"
ERROR_CONTEXT: Final = "the privileged request does not preserve its protected run's original outer deadline"
OUTSIDE_ENVIRONMENT: Final = {
    **PROVISION_ENVIRONMENT,
    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
}


class Key(StrEnum):
    """Native command facts, separate from action outcome and physical observation."""

    RECORD = "record"
    ROLE = "role"
    ACTION = "action"
    BINDING = "binding"
    COMMAND = "command"
    REQUESTED_COMMAND_END_NS = "requested_command_end_ns"
    COMMAND_END_NS = "command_end_ns"
    MONOTONIC_NS = "monotonic_ns"
    SEQUENCE = "sequence"
    PID = "pid"
    EXIT_STATUS = "exit_status"
    ERROR_CLASS = "error_class"
    STDOUT_DIAGNOSTIC = "stdout_diagnostic"
    STDERR_DIAGNOSTIC = "stderr_diagnostic"
    STDOUT_COMPLETE = "stdout_complete"
    STDOUT_SHA256 = "stdout_sha256"
    ENVIRONMENT = "environment"


class PrivilegedCommands:
    """One helper action's real provision/query executables, with no externally supplied shell text."""

    def __init__(self, owner: HelperOwner, action: Action, source_root: Path, deadline: AdmittedDeadline) -> None:
        self.owner = owner
        self.action = action
        self.source_root = source_root
        self.deadline = deadline
        self.journal_fd = -1
        self.sequence = 0
        self._processes: list[subprocess.Popen[bytes]] = []
        self._environment = dict(OUTSIDE_ENVIRONMENT)
        if action is Action.PROVISION:
            # TMPDIR-aware host tools, including dpkg-deb's control reader, use the original run directory.
            self._environment["TMPDIR"] = PARENT_DESCRIPTOR.format(
                pid=owner.journal.binding.controller.pid, descriptor=owner.inherited_directory_fd
            )

    @property
    def processes(self) -> tuple[subprocess.Popen[bytes], ...]:
        """Original native handles, including a process whose started receipt or bounded wait failed."""
        return tuple(self._processes)

    def _open(self) -> None:
        if self.journal_fd >= 0:
            return
        self.owner.require_original_parent()
        try:
            self.journal_fd = os.open(
                COMMAND_JOURNAL.format(action=self.action),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.owner.journal.directory_fd,
            )
        except FileExistsError as error:
            raise RuntimeError(ERROR_DUPLICATE) from error
        _append(
            self.journal_fd,
            {
                Key.ROLE: Role.PRIVILEGED.value,
                Key.ACTION: self.action.value,
                Key.RECORD: Record.INTENT.value,
                Key.BINDING: self.owner.journal.owner_record,
                Key.ENVIRONMENT: dict(self._environment),
                Cutoff.OUTER_END_NS: self.deadline.outer_end_ns,
                Cutoff.VECTOR_END_NS: self.deadline.vector_end_ns,
                Cutoff.COMMAND_END_NS: self.deadline.command_end_ns,
            },
        )
        os.fsync(self.owner.journal.directory_fd)

    def _started(self, pid: int) -> None:
        _append(
            self.journal_fd,
            {
                Key.RECORD: Record.STARTED.value,
                Key.SEQUENCE: self.sequence,
                Key.PID: pid,
                Key.MONOTONIC_NS: time.monotonic_ns(),
            },
        )

    def run(self, argv: tuple[str, ...], end_ns: int) -> int | None:
        """Keep the real native status; diagnostic truncation does not turn a mutation into failure."""
        return self.query(argv, end_ns).status

    def bind_action_end(self, original_command_end: int) -> None:
        """Carry the journal's action cutoff into every ensuing native producer command without widening it."""
        end = original_command_end
        if self.deadline.command_end_ns is not None:
            end = min(end, self.deadline.command_end_ns)
        self.deadline = AdmittedDeadline(self.deadline.outer_end_ns, self.deadline.vector_end_ns, end)

    def query(self, argv: tuple[str, ...], end_ns: int) -> NativeRead:
        """Record intent, native start and outcome under the same original absolute cutoff."""
        end = min(end_ns, self.deadline.effective_end())
        if time.monotonic_ns() >= end:
            raise TimeoutError(ERROR_DEADLINE)
        self._open()
        self.sequence += 1
        stdout_fd = -1
        stderr_fd = -1
        try:
            stdout_fd = os.open(
                COMMAND_STDOUT.format(action=self.action, sequence=self.sequence),
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.owner.journal.directory_fd,
            )
            stderr_fd = os.open(
                COMMAND_STDERR.format(action=self.action, sequence=self.sequence),
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.owner.journal.directory_fd,
            )
            _append(
                self.journal_fd,
                {
                    Key.RECORD: Record.INTENT.value,
                    Key.SEQUENCE: self.sequence,
                    Key.COMMAND: list(argv),
                    Key.REQUESTED_COMMAND_END_NS: end_ns,
                    Key.COMMAND_END_NS: end,
                    Key.MONOTONIC_NS: time.monotonic_ns(),
                },
            )
            os.fsync(self.owner.journal.directory_fd)
            try:
                self.owner.require_original_parent()
                status = execute_native(
                    argv,
                    cwd=self.source_root,
                    environment=self._environment,
                    stdout_fd=stdout_fd,
                    stderr_fd=stderr_fd,
                    end_ns=end,
                    started=self._started,
                    preserve=self._processes.append,
                )
            except BaseException as error:
                try:
                    _append(
                        self.journal_fd,
                        {
                            Key.RECORD: Record.UNKNOWN.value,
                            Key.SEQUENCE: self.sequence,
                            Key.ERROR_CLASS: type(error).__name__,
                            Key.MONOTONIC_NS: time.monotonic_ns(),
                        },
                    )
                except (OSError, ValueError) as secondary:
                    error.add_note(ERROR_JOURNAL.format(error_class=type(secondary).__name__))
                raise
            stdout, complete = read_native_stdout(stdout_fd)
            late = time.monotonic_ns() >= end
            outcome = Record.UNKNOWN if late else Record.ACKNOWLEDGED if status == 0 else Record.FAILED
            _append(
                self.journal_fd,
                {
                    Key.RECORD: outcome.value,
                    Key.SEQUENCE: self.sequence,
                    Key.EXIT_STATUS: status,
                    Key.MONOTONIC_NS: time.monotonic_ns(),
                    Key.STDOUT_DIAGNOSTIC: _output(stdout_fd),
                    Key.STDERR_DIAGNOSTIC: _output(stderr_fd),
                    Key.STDOUT_COMPLETE: complete,
                    Key.STDOUT_SHA256: hashlib.sha256(stdout).hexdigest() if complete else None,
                },
            )
            if late:
                raise TimeoutError(ERROR_DEADLINE)
            return NativeRead(status, stdout, complete)
        finally:
            close_evidence_descriptors(stderr_fd, stdout_fd)

    def close(self) -> None:
        """Close only the command journal; original processes stay available for the owner's bounded closure."""
        close_evidence_descriptors(self.journal_fd)


@dataclass(frozen=True)
class PrivilegedAction:
    """Protected intake and the actual source-admission/native-adapter composition for one action."""

    owner: HelperOwner
    commands: PrivilegedCommands
    admission: ActionAdmission
    guest_root_fd: int | None = None
    guest_manifest_bytes: bytes | None = None
    previous_manifest_digest: str | None = None

    @classmethod
    def load(
        cls,
        manifest: Path,
        manifest_digest: str,
        inherited_directory_fd: int,
        action: Action,
        deadline: AdmittedDeadline,
        maximum_seconds: int,
        qualification_vector: str | None,
        guest_root_fd: int | None = None,
        guest_manifest_digest: str | None = None,
        previous_manifest_digest: str | None = None,
    ) -> PrivilegedAction:
        """Load only protected inherited inputs; caller-supplied bounds can narrow the original run."""
        owner = HelperOwner.load(manifest, manifest_digest, inherited_directory_fd, ACTUAL_SOURCE_ROOT)
        try:
            if deadline.outer_end_ns != owner.journal.deadline.end_ns:
                raise ValueError(ERROR_CONTEXT)
            source = SourceAdmission(owner.realization_bytes, ACTUAL_SOURCE_ROOT, owner.package, owner.journal.binding)
            commands = PrivilegedCommands(owner, action, ACTUAL_SOURCE_ROOT, deadline)
            admission = ActionAdmission(
                owner,
                source,
                action,
                commands.query,
                maximum_seconds,
                deadline.vector_end_ns,
                deadline.command_end_ns,
                qualification_vector,
            )
            guest_data = None
            if action in (Action.GUEST_SETUP, Action.START_PAYLOAD, Action.POWEROFF):
                if guest_root_fd is None or guest_manifest_digest is None:
                    raise ValueError(ERROR_CONTEXT)
                guest_data = read_guest_input(owner, guest_root_fd, guest_manifest_digest, action=action)
                if (action is Action.START_PAYLOAD) != (previous_manifest_digest is not None):
                    raise ValueError(ERROR_CONTEXT)
                guest_record = parse_object(guest_data)
                original = AdmittedDeadline.from_record(guest_record, require_vector=qualification_vector is not None)
                if (
                    original.outer_end_ns != deadline.outer_end_ns
                    or original.vector_end_ns != deadline.vector_end_ns
                    or original.effective_end() < deadline.effective_end()
                    or guest_record.get("qualification_vector") != qualification_vector
                ):
                    raise ValueError(ERROR_CONTEXT)
            elif guest_root_fd is not None or guest_manifest_digest is not None or previous_manifest_digest is not None:
                raise ValueError(ERROR_CONTEXT)
            return cls(owner, commands, admission, guest_root_fd, guest_data, previous_manifest_digest)
        except BaseException:
            owner.close()
            raise

    def perform(self, operation: Callable[[int], ActionResult]) -> ActionResult:
        """Run only the canonical dispatcher's named producer through the required source guard."""

        def bounded(original_command_end: int) -> ActionResult:
            self.commands.bind_action_end(original_command_end)
            return operation(original_command_end)

        return self.admission.perform(bounded)

    def close(self) -> None:
        """Close command and ownership descriptors while preserving a primary failure."""
        try:
            self.commands.close()
        finally:
            try:
                self.owner.close()
            finally:
                if self.guest_root_fd is not None:
                    close_evidence_descriptors(self.guest_root_fd)

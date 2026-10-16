"""Guest identity checks and the separate one-shot normal-poweroff endpoint."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    QUALIFICATION_DIGEST,
    RECIPE_DIGEST,
    STATIC_DIGEST,
    AdmittedDeadline,
    Cutoff,
    JsonObject,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    require_hex,
    text,
)

UTF8: Final = "utf-8"
NEWLINE: Final = b"\n"
MANIFEST: Final = Path("/var/lib/teleclaude-runtime-acceptance/manifest.json")
STATIC_DIRECTORY: Final = MANIFEST.parent / "static"
SOURCE_ROOT: Final = Path("/srv/teleclaude-candidate")
GUEST_BOOT: Final = Path("/proc/sys/kernel/random/boot_id")
UID_MAP: Final = Path("/proc/self/uid_map")
GID_MAP: Final = Path("/proc/self/gid_map")
PID_NAMESPACE: Final = Path("/proc/self/ns/pid")
CGROUP_NAMESPACE: Final = Path("/proc/self/ns/cgroup")
POWER_COMMAND: Final = ("/usr/bin/systemctl", "--no-block", "poweroff")
POWER_UNIT: Final = "poweroff.service"
TIMEOUT_PREFIX: Final = "TimeoutStartSec="
SECONDS_SUFFIX: Final = "s"
JOURNAL: Final = "guest-poweroff.jsonl"
STDOUT: Final = "guest-poweroff.stdout"
STDERR: Final = "guest-poweroff.stderr"
MANIFEST_BYTES: Final = 1024 * 1024
OUTPUT_BYTES: Final = 4096
NANOSECONDS: Final = 1_000_000_000
JSON_SEPARATORS: Final = (",", ":")
DECODE_REPLACEMENT: Final = "replace"
SECONDARY_ERROR: Final = "preserving guest shutdown uncertainty also failed: {error_class}"
CLOSE_ERROR: Final = "closing guest shutdown evidence failed: {error_class}"
CLOSE_FAILURES: Final = "guest shutdown evidence descriptor failures"
POWER_ENVIRONMENT: Final = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
}
SCHEMA_VERSION: Final = 1
REQUIRED_HELPER_SOURCES: Final = frozenset(
    {"tools/ci/runtime_acceptance.py", "tools/ci/enclosure_guest.py", "tools/ci/enclosure_contract.py"}
)
ERROR_CONTEXT: Final = "guest role identity, source, namespace or protected manifest does not match admission"
ERROR_DUPLICATE: Final = "the guest poweroff endpoint already has an intent; no second call is admitted"
ERROR_BUDGET: Final = "the original guest command/outer allowance is exhausted"


class Purpose(StrEnum):
    """Separate execution purposes, with no qualification-to-application credit."""

    APPLICATION = "application"
    QUALIFICATION = "qualification"


class Role(StrEnum):
    """The roles selected by the reviewed harness entry protocol."""

    SUPERVISOR = "supervisor"
    PAYLOAD = "payload"
    GUEST_SETUP = "guest-setup"
    GUEST_POWEROFF = "guest-poweroff"
    PRIVILEGED = "privileged"
    QUALIFICATION = "qualification"
    ROLLING_INPUT_OBSERVER = "rolling-input-observer"


ROOT_GUEST_ROLES: Final = frozenset({Role.GUEST_SETUP, Role.GUEST_POWEROFF})
QUALIFICATION_GUEST_VECTORS: Final = {Role.GUEST_SETUP: "Q2", Role.GUEST_POWEROFF: "Q4"}


class Key(StrEnum):
    """Internal protected guest-manifest and shutdown evidence fields."""

    SCHEMA_VERSION = "schema_version"
    RUN_TOKEN = "run_token"
    SOURCE_COMMIT = "source_commit"
    SOURCE_TREE = "source_tree"
    STATIC_LOCK_SHA256 = "static_lock_sha256"
    RECIPE_SHA256 = "recipe_sha256"
    QUALIFICATION_SHA256 = "qualification_sha256"
    MANIFEST_SHA256 = "manifest_sha256"
    REALIZATION_SHA256 = "realization_sha256"
    PURPOSE = "purpose"
    QUALIFICATION_VECTOR = "qualification_vector"
    ADMISSION_SEAL_SHA256 = "admission_seal_sha256"
    GUEST_BOOT_ID = "guest_boot_id"
    UID_MAP = "uid_map"
    GID_MAP = "gid_map"
    PID_NAMESPACE = "pid_namespace"
    CGROUP_NAMESPACE = "cgroup_namespace"
    HOST_PID_NAMESPACE = "host_pid_namespace"
    HOST_CGROUP_NAMESPACE = "host_cgroup_namespace"
    SOURCE_FILES = "source_files"
    SELECTED_SCENARIOS = "selected_scenarios"
    GUEST = "guest"
    ACCOUNT = "account"
    UID = "uid"
    GID = "gid"
    RECORD = "record"
    MONOTONIC_NS = "monotonic_ns"
    COMMAND = "command"
    EFFECTIVE_COMMAND_END_NS = "effective_command_end_ns"
    PID = "pid"
    EXIT_STATUS = "exit_status"
    ERROR_CLASS = "error_class"
    STDOUT = "stdout"
    STDERR = "stderr"
    TRUNCATED = "truncated"
    AVAILABLE_BYTES = "available_bytes"
    TEXT = "text"


class Record(StrEnum):
    """Shutdown request facts; acknowledgment is never physical-exit proof."""

    INTENT = "intent"
    STARTED = "started"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GuestContext:
    """A protected outside-produced binding, verified again before guest effects."""

    manifest_bytes: bytes
    package: StaticPackage

    @property
    def record(self) -> JsonObject:
        """Decode a fresh view of the immutable binding rather than exposing mutable authority."""
        return parse_object(self.manifest_bytes)

    @classmethod
    def load(cls, manifest: Path, role: Role = Role.GUEST_POWEROFF) -> GuestContext:
        """Read only the declared root-owned guest manifest and its exact static/source basis."""
        if manifest != MANIFEST or os.geteuid() != 0 or role not in ROOT_GUEST_ROLES:
            raise ValueError(ERROR_CONTEXT)
        data = _read_manifest()
        package = StaticPackage.load(STATIC_DIRECTORY, SOURCE_ROOT)
        context = cls(data, package)
        context.verify(role)
        return context

    @classmethod
    def load_payload(cls, manifest: Path) -> GuestContext:
        """Read the same protected binding as the declared ordinary guest account."""
        if manifest != MANIFEST:
            raise ValueError(ERROR_CONTEXT)
        data = _read_manifest()
        package = StaticPackage.load(STATIC_DIRECTORY, SOURCE_ROOT)
        context = cls(data, package)
        context.verify_payload()
        return context

    def verify(self, role: Role) -> None:
        """Require actual nonidentity namespaces, exact source bytes and the original deadline."""
        if role not in ROOT_GUEST_ROLES and role is not Role.PAYLOAD:
            raise ValueError(ERROR_CONTEXT)
        if _read_manifest() != self.manifest_bytes or (
            hashlib.sha256(self.package.lock_bytes).hexdigest() != STATIC_DIGEST
            or hashlib.sha256(self.package.recipe_bytes).hexdigest() != RECIPE_DIGEST
            or hashlib.sha256(self.package.qualification_bytes).hexdigest() != QUALIFICATION_DIGEST
        ):
            raise ValueError(ERROR_CONTEXT)
        record = self.record
        if positive_integer(record, Key.SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ValueError(ERROR_CONTEXT)
        for key, length in (
            (Key.RUN_TOKEN, 32),
            (Key.SOURCE_COMMIT, 40),
            (Key.SOURCE_TREE, 40),
            (Key.REALIZATION_SHA256, 64),
            (Key.ADMISSION_SEAL_SHA256, 64),
        ):
            require_hex(text(record, key), length)
        if (
            record.get(Key.STATIC_LOCK_SHA256) != STATIC_DIGEST
            or record.get(Key.RECIPE_SHA256) != RECIPE_DIGEST
            or record.get(Key.QUALIFICATION_SHA256) != QUALIFICATION_DIGEST
        ):
            raise ValueError(ERROR_CONTEXT)
        purpose = Purpose(text(record, Key.PURPOSE))
        if purpose is Purpose.QUALIFICATION:
            expected_vector = QUALIFICATION_GUEST_VECTORS.get(role)
            if expected_vector is None or record.get(Key.QUALIFICATION_VECTOR) != expected_vector:
                raise ValueError(ERROR_CONTEXT)
        if GUEST_BOOT.read_text(encoding=UTF8).strip() != text(record, Key.GUEST_BOOT_ID):
            raise ValueError(ERROR_CONTEXT)
        for path, key in ((UID_MAP, Key.UID_MAP), (GID_MAP, Key.GID_MAP)):
            actual = path.read_text(encoding=UTF8)
            if actual != text(record, key):
                raise ValueError(ERROR_CONTEXT)
            _nonidentity_map(actual)
        for path, key, outside in (
            (PID_NAMESPACE, Key.PID_NAMESPACE, Key.HOST_PID_NAMESPACE),
            (CGROUP_NAMESPACE, Key.CGROUP_NAMESPACE, Key.HOST_CGROUP_NAMESPACE),
        ):
            actual_namespace = os.readlink(path)
            if actual_namespace != text(record, key) or actual_namespace == text(record, outside):
                raise ValueError(ERROR_CONTEXT)
        files = object_value(record[Key.SOURCE_FILES])
        if not REQUIRED_HELPER_SOURCES <= set(files):
            raise ValueError(ERROR_CONTEXT)
        root = SOURCE_ROOT.resolve(strict=True)
        for relative, expected in files.items():
            if not isinstance(expected, str):
                raise ValueError(ERROR_CONTEXT)
            require_hex(expected, 64)
            path = (root / relative).resolve(strict=True)
            if (
                Path(relative).is_absolute()
                or not path.is_relative_to(root)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                raise ValueError(ERROR_CONTEXT)
        self.package.validate_source(root)
        if time.monotonic_ns() >= self.admitted_deadline().effective_end():
            raise TimeoutError(ERROR_BUDGET)

    def admitted_deadline(self) -> AdmittedDeadline:
        """Read the original outside-admitted outer/vector/command bounds without substitution."""
        return AdmittedDeadline.from_record(
            self.record, require_vector=Purpose(text(self.record, Key.PURPOSE)) is Purpose.QUALIFICATION
        )

    def verify_payload(self) -> None:
        """Require application purpose and the recipe's actual ordinary UID/GID before product work."""
        self.verify(Role.PAYLOAD)
        recipe = parse_object(self.package.recipe_bytes)
        account = object_value(object_value(recipe[Key.GUEST])[Key.ACCOUNT])
        if (
            Purpose(text(self.record, Key.PURPOSE)) is not Purpose.APPLICATION
            or os.geteuid() != positive_integer(account, Key.UID)
            or os.getegid() != positive_integer(account, Key.GID)
        ):
            raise ValueError(ERROR_CONTEXT)

    def verify_request(self, root: Path, commit: str, tree: str, selection: frozenset[str]) -> None:
        """Bind the public payload request to the protected candidate and effective selection."""
        self.verify_payload()
        record = self.record
        selected = record.get(Key.SELECTED_SCENARIOS)
        if not isinstance(selected, list):
            raise ValueError(ERROR_CONTEXT)
        names: list[str] = []
        for value in selected:
            if not isinstance(value, str):
                raise ValueError(ERROR_CONTEXT)
            names.append(value)
        if (
            root.resolve(strict=True) != SOURCE_ROOT
            or commit != text(record, Key.SOURCE_COMMIT)
            or tree != text(record, Key.SOURCE_TREE)
            or len(names) != len(set(names))
            or frozenset(names) != selection
        ):
            raise ValueError(ERROR_CONTEXT)

    def command_end(self, unit_name: str = POWER_UNIT) -> int:
        """Intersect all admitted cutoffs with the selected static guest unit's own allowance."""
        rendered = self.package.render(
            run_token=text(self.record, Key.RUN_TOKEN),
            candidate_sha=text(self.record, Key.SOURCE_COMMIT),
            candidate_tree=text(self.record, Key.SOURCE_TREE),
            selection="",
        )[unit_name]
        declarations = [
            line[len(TIMEOUT_PREFIX) :]
            for line in rendered.decode(UTF8).splitlines()
            if line.startswith(TIMEOUT_PREFIX)
        ]
        if len(declarations) != 1 or not declarations[0].endswith(SECONDS_SUFFIX):
            raise ValueError(ERROR_CONTEXT)
        seconds = int(declarations[0][: -len(SECONDS_SUFFIX)])
        if seconds <= 0:
            raise ValueError(ERROR_CONTEXT)
        return self.admitted_deadline().command_end(seconds)


def _read_manifest() -> bytes:
    parent_fd = os.open(MANIFEST.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        directory = os.fstat(parent_fd)
        if directory.st_uid != 0 or stat.S_IMODE(directory.st_mode) & 0o022:
            raise ValueError(ERROR_CONTEXT)
        descriptor = os.open(MANIFEST.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            owned = os.fstat(descriptor)
            if (
                not stat.S_ISREG(owned.st_mode)
                or owned.st_uid != 0
                or owned.st_nlink != 1
                or stat.S_IMODE(owned.st_mode) & 0o022
            ):
                raise ValueError(ERROR_CONTEXT)
            data = os.read(descriptor, MANIFEST_BYTES + 1)
            if len(data) > MANIFEST_BYTES:
                raise ValueError(ERROR_CONTEXT)
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _nonidentity_map(raw: str) -> None:
    rows: list[tuple[int, int, int]] = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(ERROR_CONTEXT)
        inside, outside, count = (int(part) for part in parts)
        if inside < 0 or outside < 0 or count <= 0:
            raise ValueError(ERROR_CONTEXT)
        if any(
            max(inside, old_inside) < min(inside + count, old_inside + old_count) for old_inside, _, old_count in rows
        ):
            raise ValueError(ERROR_CONTEXT)
        rows.append((inside, outside, count))
    if not rows or not any(inside == 0 and outside != 0 for inside, outside, _ in rows):
        raise ValueError(ERROR_CONTEXT)


def _append(descriptor: int, record: JsonObject) -> None:
    data = json.dumps(record, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False).encode(UTF8) + NEWLINE
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError(ERROR_CONTEXT)
        offset += written
    os.fsync(descriptor)


def _output(descriptor: int) -> JsonObject:
    data = os.pread(descriptor, OUTPUT_BYTES + 1, 0)
    return {
        Key.AVAILABLE_BYTES: os.fstat(descriptor).st_size,
        Key.TRUNCATED: len(data) > OUTPUT_BYTES,
        Key.TEXT: data[:OUTPUT_BYTES].decode(UTF8, errors=DECODE_REPLACEMENT),
    }


def request_guest_poweroff(context: GuestContext) -> Record:
    """Request the declared endpoint once, for Q4 or payload cleanup, without claiming exit."""
    if os.geteuid() != 0:
        raise ValueError(ERROR_CONTEXT)
    context.verify(Role.GUEST_POWEROFF)
    admitted = context.admitted_deadline()
    command_end = context.command_end()
    directory_fd = os.open(MANIFEST.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    journal_fd = -1
    stdout_fd = -1
    stderr_fd = -1
    try:
        try:
            journal_fd = os.open(
                JOURNAL, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd
            )
        except FileExistsError as error:
            raise RuntimeError(ERROR_DUPLICATE) from error
        identity: JsonObject = {
            Key.SCHEMA_VERSION: SCHEMA_VERSION,
            Key.RUN_TOKEN: text(context.record, Key.RUN_TOKEN),
            Key.SOURCE_COMMIT: text(context.record, Key.SOURCE_COMMIT),
            Key.SOURCE_TREE: text(context.record, Key.SOURCE_TREE),
            Key.REALIZATION_SHA256: text(context.record, Key.REALIZATION_SHA256),
            Key.STATIC_LOCK_SHA256: STATIC_DIGEST,
            Key.RECIPE_SHA256: RECIPE_DIGEST,
            Key.QUALIFICATION_SHA256: QUALIFICATION_DIGEST,
            Key.MANIFEST_SHA256: hashlib.sha256(context.manifest_bytes).hexdigest(),
            Key.ADMISSION_SEAL_SHA256: text(context.record, Key.ADMISSION_SEAL_SHA256),
            Key.PURPOSE: text(context.record, Key.PURPOSE),
            Key.QUALIFICATION_VECTOR: context.record.get(Key.QUALIFICATION_VECTOR),
            Key.RECORD: Record.INTENT.value,
            Key.MONOTONIC_NS: time.monotonic_ns(),
            Key.COMMAND: list(POWER_COMMAND),
            Cutoff.OUTER_END_NS: admitted.outer_end_ns,
            Cutoff.VECTOR_END_NS: admitted.vector_end_ns,
            Cutoff.COMMAND_END_NS: admitted.command_end_ns,
            Key.EFFECTIVE_COMMAND_END_NS: command_end,
        }
        _append(journal_fd, identity)
        os.fsync(directory_fd)
        stdout_fd = os.open(
            STDOUT, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd
        )
        stderr_fd = os.open(
            STDERR, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd
        )
        remaining = (command_end - time.monotonic_ns()) / NANOSECONDS
        if remaining <= 0:
            raise TimeoutError(ERROR_BUDGET)
        try:
            # The reviewed endpoint is a native guest-manager request, not an in-process application API.
            process = subprocess.Popen(
                POWER_COMMAND,
                stdin=subprocess.DEVNULL,
                stdout=stdout_fd,
                stderr=stderr_fd,
                close_fds=True,
                env=POWER_ENVIRONMENT,
            )
            _append(
                journal_fd,
                {Key.RECORD: Record.STARTED.value, Key.PID: process.pid, Key.MONOTONIC_NS: time.monotonic_ns()},
            )
            remaining = (command_end - time.monotonic_ns()) / NANOSECONDS
            if remaining <= 0:
                raise TimeoutError(ERROR_BUDGET)
            status = process.wait(timeout=remaining)
        except (OSError, TimeoutError, subprocess.TimeoutExpired) as error:
            try:
                _append(
                    journal_fd,
                    {
                        Key.RECORD: Record.UNKNOWN.value,
                        Key.ERROR_CLASS: type(error).__name__,
                        Key.MONOTONIC_NS: time.monotonic_ns(),
                    },
                )
            except (OSError, ValueError) as secondary:
                error.add_note(SECONDARY_ERROR.format(error_class=type(secondary).__name__))
            raise
        result = (
            Record.UNKNOWN
            if time.monotonic_ns() >= command_end
            else Record.ACKNOWLEDGED
            if status == 0
            else Record.FAILED
        )
        _append(
            journal_fd,
            {
                Key.RECORD: result.value,
                Key.EXIT_STATUS: status,
                Key.STDOUT: _output(stdout_fd),
                Key.STDERR: _output(stderr_fd),
                Key.MONOTONIC_NS: time.monotonic_ns(),
            },
        )
        return result
    finally:
        original = sys.exception()
        failures: list[OSError] = []
        for descriptor in (stderr_fd, stdout_fd, journal_fd, directory_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError as secondary:
                    if original is not None:
                        original.add_note(CLOSE_ERROR.format(error_class=type(secondary).__name__))
                    else:
                        failures.append(secondary)
        if failures:
            raise ExceptionGroup(CLOSE_FAILURES, failures)

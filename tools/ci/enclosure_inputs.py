"""Acquire fixed enclosure archives and stage the locked outside observer library."""

from __future__ import annotations

import hashlib
import os
import stat
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from tools.ci.enclosure_contract import (
    AdmittedDeadline,
    Cutoff,
    Field,
    JsonObject,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    require_hex,
    text,
)
from tools.ci.enclosure_data import _archive, _command, _require_time
from tools.ci.enclosure_native import NativeCommand
from tools.ci.enclosure_owner import (
    FILE_MODE,
    MANIFEST_LIMIT,
    PARENT_DESCRIPTOR,
    QUALIFICATION_INTAKE_NAME,
    HelperOwner,
    _require_private_directory,
)
from tools.ci.enclosure_owner import Key as OwnerKey

CURL: Final = "/usr/bin/curl"
CURL_ARGUMENTS: Final = (
    CURL,
    "--disable",
    "--fail",
    "--location",
    "--proto",
    "=https",
    "--proto-redir",
    "=https",
    "--retry",
    "0",
)
MAX_TIME: Final = "--max-time"
MAX_FILESIZE: Final = "--max-filesize"
OUTPUT: Final = "--output"
END_OPTIONS: Final = "--"
HTTPS: Final = "https"
READ_BINARY: Final = "rb"
SHA256: Final = "sha256"
NANOSECONDS: Final = 1_000_000_000
ERROR_INPUT: Final = "a fixed input is malformed or conflicts with another declared digest"
ERROR_OWNER: Final = "fixed acquisition requires a new private directory owned by the privileged helper"
ERROR_DEADLINE: Final = "fixed acquisition exhausted its original admitted allowance"
ERROR_ACQUISITION: Final = "fixed input acquisition failed or returned different bytes: {digest}, exit {status}"
OBSERVER_DIRECTORY: Final = "observer-library"
ZIP_EXTRACT: Final = ("-I", "-S", "-m", "zipfile", "--extract")
FIXED_INPUT_DIRECTORY: Final = "fixed-inputs"
ERROR_INTAKE: Final = "Q1 requires complete actual protected fixed inputs before Q2; no acquisition is attempted"
ERROR_INPUT_CLOSE: Final = "closing the failed read-only input intake also failed: {error_class}"
Q1_VECTOR: Final = "Q1"
SUCCEEDED: Final = "succeeded"


class Key(StrEnum):
    """The fixed archive groups and native vendor URL fields in the reviewed lock."""

    GUEST_BASE = "guest_base"
    HOST_CLOSURE = "host_closure"
    GUEST_CLOSURE = "guest_closure"
    FINAL_PACKAGES = "final_packages"
    ARCHIVE_URL = "archive_url"
    NODE = "node"
    TOOL_ARCHIVES = "tool_archives"
    NPM_TOOLS = "npm_tools"
    OBSERVER_LIBRARY = "observer_library"
    URL = "url"
    TARBALL = "tarball"
    HOST = "host"
    PYTHON_INTERPRETER = "python_interpreter"
    FILES = "files"
    DIRECTORY_FD = "directory_fd"
    DIRECTORY_DEVICE = "directory_device"
    DIRECTORY_INODE = "directory_inode"
    STARTED_NS = "started_ns"
    FINISHED_NS = "finished_ns"
    DIRECTORY_PATH = "directory_path"
    DIRECTORY_OPEN = "directory_open"
    EXPECTED_SHA256 = "expected_sha256"
    EXPECTED_BYTES = "expected_bytes"
    BEFORE = "before"
    AFTER = "after"
    DEVICE = "device"
    INODE = "inode"
    MODE = "mode"
    UID = "uid"
    GID = "gid"
    LINKS = "links"
    MODIFIED_NS = "modified_ns"
    CHANGED_NS = "changed_ns"
    ID = "id"
    STATE = "state"
    END_NS = "end_ns"
    INPUT_FACTS = "input_facts"
    MANIFEST_SHA256 = "manifest_sha256"


def _native_identity(value: os.stat_result) -> JsonObject:
    """Retain the already-read metadata; this performs no additional observation."""
    return {
        Key.DEVICE: value.st_dev,
        Key.INODE: value.st_ino,
        Key.MODE: value.st_mode,
        Key.UID: value.st_uid,
        Key.GID: value.st_gid,
        Key.LINKS: value.st_nlink,
        Field.BYTES: value.st_size,
        Key.MODIFIED_NS: value.st_mtime_ns,
        Key.CHANGED_NS: value.st_ctime_ns,
    }


@dataclass(frozen=True)
class FixedInput:
    """One vendor archive already bound by the independently reviewed static package."""

    url: str
    sha256: str
    size: int

    @classmethod
    def from_row(cls, row: JsonObject, url_key: Key) -> FixedInput:
        """Preserve the lock's declared address, bytes and authentication scope."""
        url = text(row, url_key)
        parsed = urlsplit(url)
        digest = text(row, Field.SHA256)
        require_hex(digest, 64)
        if parsed.scheme != HTTPS or not parsed.netloc or parsed.username is not None or parsed.password is not None:
            raise ValueError(ERROR_INPUT)
        return cls(url, digest, positive_integer(row, Field.BYTES))


def fixed_inputs(package: StaticPackage) -> tuple[FixedInput, ...]:
    """Enumerate the declared archives, without inventing a rolling tool resolution."""
    lock = parse_object(package.lock_bytes)
    result: dict[str, FixedInput] = {}

    def add(row: JsonObject, key: Key) -> None:
        item = FixedInput.from_row(row, key)
        previous = result.get(item.sha256)
        if previous is not None and previous != item:
            raise ValueError(ERROR_INPUT)
        result[item.sha256] = item

    add(object_value(lock[Key.GUEST_BASE]), Key.ARCHIVE_URL)
    for group in (Key.HOST_CLOSURE, Key.GUEST_CLOSURE):
        rows = object_value(lock[group])[Key.FINAL_PACKAGES]
        if not isinstance(rows, list):
            raise ValueError(ERROR_INPUT)
        for value in rows:
            row = object_value(value)
            if Key.ARCHIVE_URL in row:
                add(row, Key.ARCHIVE_URL)
    add(object_value(lock[Key.NODE]), Key.ARCHIVE_URL)
    for group in (Key.TOOL_ARCHIVES, Key.NPM_TOOLS):
        rows = lock[group]
        if not isinstance(rows, list):
            raise ValueError(ERROR_INPUT)
        for value in rows:
            row = object_value(value)
            add(row, Key.TARBALL if Key.TARBALL in row else Key.URL)
    add(object_value(lock[Key.OBSERVER_LIBRARY]), Key.URL)
    return tuple(result.values())


@dataclass(frozen=True)
class FixedInputIntake:
    """Actual Q1 archive reads and the retained original directory, without acquisition authority."""

    directory_fd: int
    facts: JsonObject

    @classmethod
    def authenticate(
        cls,
        package: StaticPackage,
        directory: Path,
        deadline: AdmittedDeadline,
        facts: JsonObject,
        progress: Callable[[], None],
    ) -> FixedInputIntake:
        """Update the owner's evidence prefix before each read; never fetch, repair or retry an input."""
        files: JsonObject = {}
        facts.update(
            {
                Key.DIRECTORY_PATH: str(directory),
                Key.DIRECTORY_OPEN: False,
                Key.STARTED_NS: time.monotonic_ns(),
                Cutoff.OUTER_END_NS: deadline.outer_end_ns,
                Cutoff.VECTOR_END_NS: deadline.vector_end_ns,
                Cutoff.COMMAND_END_NS: deadline.command_end_ns,
                Key.FILES: files,
            }
        )
        descriptor = -1
        try:
            progress()
            _require_time(deadline)
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            facts[Key.DIRECTORY_FD] = descriptor
            facts[Key.DIRECTORY_OPEN] = True
            native = os.fstat(descriptor)
            facts[Key.BEFORE] = _native_identity(native)
            facts[Key.DIRECTORY_DEVICE] = native.st_dev
            facts[Key.DIRECTORY_INODE] = native.st_ino
            if not stat.S_ISDIR(native.st_mode) or native.st_uid != 0 or native.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ValueError(ERROR_INTAKE)
            for item in fixed_inputs(package):
                progress()
                _require_time(deadline)
                observed: JsonObject = {
                    Key.EXPECTED_SHA256: item.sha256,
                    Key.EXPECTED_BYTES: item.size,
                    Field.SHA256: None,
                    Field.BYTES: None,
                    Key.STARTED_NS: time.monotonic_ns(),
                }
                files[item.sha256] = observed
                leaf = -1
                failure: BaseException | None = None
                try:
                    leaf = os.open(
                        item.sha256, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=descriptor
                    )
                    before = os.fstat(leaf)
                    observed[Key.BEFORE] = _native_identity(before)
                    observed[Field.BYTES] = before.st_size
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_uid != 0
                        or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                        or before.st_size != item.size
                    ):
                        raise ValueError(ERROR_INTAKE)
                    with os.fdopen(os.dup(leaf), READ_BINARY) as handle:
                        digest = hashlib.file_digest(handle, SHA256).hexdigest()
                    observed[Field.SHA256] = digest
                    after = os.fstat(leaf)
                    observed[Key.AFTER] = _native_identity(after)
                    if digest != item.sha256 or observed[Key.BEFORE] != observed[Key.AFTER]:
                        raise ValueError(ERROR_INTAKE)
                    progress()
                    _require_time(deadline)
                except BaseException as error:
                    failure = error
                    raise
                finally:
                    observed[Key.FINISHED_NS] = time.monotonic_ns()
                    if leaf >= 0:
                        try:
                            os.close(leaf)
                        except OSError as secondary:
                            if failure is None:
                                raise
                            failure.add_note(ERROR_INPUT_CLOSE.format(error_class=type(secondary).__name__))
            progress()
            _require_time(deadline)
            return cls(descriptor, facts)
        except BaseException as error:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                    facts[Key.DIRECTORY_OPEN] = False
                except OSError as secondary:
                    facts[Key.DIRECTORY_OPEN] = None
                    error.add_note(ERROR_INPUT_CLOSE.format(error_class=type(secondary).__name__))
            raise
        finally:
            facts[Key.FINISHED_NS] = time.monotonic_ns()


def qualification_input_paths(owner: HelperOwner, deadline: AdmittedDeadline) -> dict[str, Path]:
    """Consume actual Q1 byte facts through the original controller's retained directory capability."""
    owner.require_original_parent()
    name = text(parse_object(owner.manifest_bytes), OwnerKey.OFFLINE_INPUTS)
    if name != QUALIFICATION_INTAKE_NAME:
        raise ValueError(ERROR_INTAKE)
    _require_time(deadline)
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=owner.journal.directory_fd
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) != FILE_MODE
            or before.st_nlink != 1
            or not 0 < before.st_size <= MANIFEST_LIMIT
        ):
            raise ValueError(ERROR_INTAKE)
        data = os.pread(descriptor, MANIFEST_LIMIT + 1, 0)
        after = os.fstat(descriptor)
        if len(data) != before.st_size or _native_identity(before) != _native_identity(after):
            raise ValueError(ERROR_INTAKE)
    finally:
        os.close(descriptor)
    proof = parse_object(data)
    if (
        proof.get(Key.ID) != Q1_VECTOR
        or proof.get(Key.STATE) != SUCCEEDED
        or proof.get(OwnerKey.BINDING) != owner.journal.owner_record
        or proof.get(Key.MANIFEST_SHA256) != hashlib.sha256(owner.manifest_bytes).hexdigest()
    ):
        raise ValueError(ERROR_INTAKE)
    record = object_value(proof[Key.INPUT_FACTS])
    first = AdmittedDeadline.from_record(record, require_vector=True)
    if (
        first.outer_end_ns != deadline.outer_end_ns
        or proof.get(Key.END_NS) != first.effective_end()
        or record.get(Key.DIRECTORY_OPEN) is not True
        or not positive_integer(record, Key.STARTED_NS)
        <= positive_integer(record, Key.FINISHED_NS)
        <= positive_integer(proof, Key.FINISHED_NS)
        < first.effective_end()
        or positive_integer(record, Key.FINISHED_NS) >= time.monotonic_ns()
    ):
        raise ValueError(ERROR_INTAKE)
    root = Path(
        PARENT_DESCRIPTOR.format(
            pid=owner.journal.binding.controller.pid, descriptor=positive_integer(record, Key.DIRECTORY_FD)
        )
    )
    native = root.stat()
    if (
        not stat.S_ISDIR(native.st_mode)
        or native.st_uid != 0
        or native.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or type(record.get(Key.DIRECTORY_DEVICE)) is not int
        or type(record.get(Key.DIRECTORY_INODE)) is not int
        or native.st_dev != record[Key.DIRECTORY_DEVICE]
        or native.st_ino != record[Key.DIRECTORY_INODE]
    ):
        raise ValueError(ERROR_INTAKE)
    files = object_value(record[Key.FILES])
    items = fixed_inputs(owner.package)
    if set(files) != {item.sha256 for item in items}:
        raise ValueError(ERROR_INTAKE)
    result: dict[str, Path] = {}
    for item in items:
        row = object_value(files[item.sha256])
        if text(row, Field.SHA256) != item.sha256 or positive_integer(row, Field.BYTES) != item.size:
            raise ValueError(ERROR_INTAKE)
        result[item.sha256] = root / item.sha256
    _require_time(deadline)
    return result


def acquire_fixed_inputs(
    package: StaticPackage, directory: Path, run: NativeCommand, deadline: AdmittedDeadline
) -> dict[str, Path]:
    """Fetch each unique declared archive once, preserving failed prefixes and never retrying."""
    if os.geteuid() != 0:
        raise ValueError(ERROR_OWNER)
    items = fixed_inputs(package)
    recipe = parse_object(package.recipe_bytes)
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    deadline.command_end(cap)
    directory.mkdir(mode=0o700)
    owner = directory.lstat()
    if not stat.S_ISDIR(owner.st_mode) or owner.st_uid != 0 or stat.S_IMODE(owner.st_mode) != 0o700:
        raise ValueError(ERROR_OWNER)
    result: dict[str, Path] = {}
    for item in items:
        end = deadline.command_end(cap)
        remaining = (end - time.monotonic_ns()) / NANOSECONDS
        if remaining <= 0:
            raise TimeoutError(ERROR_DEADLINE)
        destination = directory / item.sha256
        # curl owns HTTPS and redirects. The closed declarations supply every address and destination.
        status = run(
            (
                *CURL_ARGUMENTS,
                MAX_TIME,
                str(remaining),
                MAX_FILESIZE,
                str(item.size),
                OUTPUT,
                str(destination),
                END_OPTIONS,
                item.url,
            ),
            end,
        )
        if time.monotonic_ns() >= end:
            raise TimeoutError(ERROR_DEADLINE)
        if status != 0:
            raise RuntimeError(ERROR_ACQUISITION.format(digest=item.sha256, status=status))
        with destination.open(mode=READ_BINARY) as handle:
            before = os.fstat(handle.fileno())
            digest = hashlib.file_digest(handle, SHA256).hexdigest()
            after = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_uid != 0
            or after.st_nlink != 1
            or after.st_size != item.size
            or digest != item.sha256
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        ):
            raise ValueError(ERROR_ACQUISITION.format(digest=item.sha256, status=status))
        if time.monotonic_ns() >= end:
            raise TimeoutError(ERROR_DEADLINE)
        result[item.sha256] = destination
    return result


def observer_library_inventory(
    package: StaticPackage, inputs: Mapping[str, Path], deadline: AdmittedDeadline
) -> JsonObject:
    """Derive source-realization member identities from the fixed wheel, without importing or extracting it."""
    library = object_value(parse_object(package.lock_bytes)[Key.OBSERVER_LIBRARY])
    archive = _archive(library, inputs, deadline)
    files: JsonObject = {}
    with zipfile.ZipFile(archive) as wheel:
        for member in wheel.infolist():
            _require_time(deadline)
            if member.is_dir():
                continue
            path = Path(member.filename)
            if (
                path.is_absolute()
                or os.pardir in path.parts
                or path.as_posix() != member.filename
                or member.filename in files
            ):
                raise ValueError(ERROR_INPUT)
            data = wheel.read(member)
            files[member.filename] = {Field.SHA256: hashlib.sha256(data).hexdigest(), Field.BYTES: len(data)}
    _require_time(deadline)
    return {Field.SHA256: text(library, Field.SHA256), Key.FILES: files}


def stage_observer_library(
    owner: HelperOwner,
    inputs: Mapping[str, Path],
    run: NativeCommand,
    deadline: AdmittedDeadline,
) -> Path:
    """Extract the one authenticated wheel as data, without executing or installing its package."""
    controller = owner.journal.binding.controller
    if deadline.outer_end_ns != owner.journal.deadline.end_ns:
        raise ValueError(ERROR_OWNER)
    deadline = AdmittedDeadline(
        deadline.outer_end_ns,
        deadline.vector_end_ns,
        min(deadline.effective_end(), deadline.outer_end_ns - owner.journal.deadline.reserve_ns),
    )
    _require_time(deadline)
    owner.require_original_parent()
    _require_private_directory(owner.journal.directory_fd)
    package = owner.package
    library = object_value(parse_object(package.lock_bytes)[Key.OBSERVER_LIBRARY])
    archive = _archive(library, inputs, deadline)
    recipe = parse_object(package.recipe_bytes)
    interpreter = text(object_value(recipe[Key.HOST]), Key.PYTHON_INTERPRETER)
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    deadline.command_end(cap)
    # mkdir is exclusive: a partial prior extraction is retained, never reused.
    os.mkdir(OBSERVER_DIRECTORY, mode=0o700, dir_fd=owner.journal.directory_fd)
    os.fsync(owner.journal.directory_fd)
    directory = Path(PARENT_DESCRIPTOR.format(pid=controller.pid, descriptor=owner.inherited_directory_fd))
    destination = directory / OBSERVER_DIRECTORY
    # The existing bounded adapter runs only the locked interpreter's stdlib ZIP
    # command; this does not import wheel code or connect a manager observer.
    _command((interpreter, *ZIP_EXTRACT, str(archive), str(destination)), run, deadline, cap)
    owner.require_original_parent()
    return destination

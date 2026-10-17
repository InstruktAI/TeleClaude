"""Outside supervisor ownership, before any host unit or guest resource is created."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    QUALIFICATION_DIGEST,
    QUALIFICATION_FILE,
    RECIPE_DIGEST,
    RECIPE_FILE,
    SELECTION_CHARACTERS,
    STATIC_DIGEST,
    STATIC_FILE,
    Deadline,
    Field,
    JsonObject,
    JsonValue,
    Parameter,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    require_hex,
    text,
)
from tools.ci.enclosure_guest import Purpose, close_evidence_descriptors
from tools.ci.enclosure_journal import ActionJournal, Binding, Controller
from tools.ci.enclosure_journal import Key as JournalKey

STATE_ROOT: Final = Path("/var/lib/teleclaude-runtime-acceptance")
MANIFEST_NAME: Final = "manifest.json"
REALIZATION_NAME: Final = "realization.json"
UTF8: Final = "utf-8"
JSON_SEPARATORS: Final = (",", ":")
EXCLUSIVE_BINARY: Final = "wb"
NONCE_BYTES: Final = 32
SELECTION_SEPARATOR: Final = ","
SCENARIO_CHARACTERS: Final = SELECTION_CHARACTERS - {SELECTION_SEPARATOR}
ROOT_MODE: Final = 0o700
FILE_MODE: Final = 0o600
PRIVATE_UMASK: Final = 0o077
MANIFEST_LIMIT: Final = 1024 * 1024
PARENT_DESCRIPTOR: Final = "/proc/{pid}/fd/{descriptor}"
ERROR_OWNER: Final = "outside ownership requires the original privileged controller and protected new run directory"
ERROR_WORKFLOW: Final = "the immutable hosted workflow/run attempt identity or provider image assertion is unavailable"
ERROR_MANIFEST: Final = "the initial protected run manifest could not be durably read back"
ERROR_INPUT: Final = "protected run input {name} is missing, changed or could not be durably read back"
ERROR_PREFIX: Final = "initial ownership did not complete at {path}; this step invoked no unit or guest creation"


class Environment(StrEnum):
    """Hosted-run identity assertions retained from their actual supervisor intake."""

    REPOSITORY = "GITHUB_REPOSITORY"
    WORKFLOW_REF = "GITHUB_WORKFLOW_REF"
    RUN_ID = "GITHUB_RUN_ID"
    RUN_ATTEMPT = "GITHUB_RUN_ATTEMPT"
    IMAGE_VERSION = "ImageVersion"


class Key(StrEnum):
    """Initial run-owned metadata; neither review approval nor runtime proof is encoded here."""

    HOST = "host"
    PARENT_NAME = "parent_name"
    INSTANCE_NAME = "instance_name"
    ROOTFS = "rootfs"
    WORKFLOW = "workflow"
    IMAGE_VERSION = "image_version"
    BINDING = "binding"
    PURPOSE = "purpose"
    PARENT_UNIT = "parent_unit"
    GUEST_UNIT = "guest_unit"
    CREATED_NS = "created_ns"
    DIRECTORY_FD = "directory_fd"
    INPUTS = "inputs"
    SELECTED_SCENARIOS = "selected_scenarios"


@dataclass(frozen=True)
class WorkflowIdentity:
    """Provider assertions, with no claim that their values prove the actual substrate."""

    repository: str
    workflow_ref: str
    run_id: str
    run_attempt: str
    image_version: str

    @classmethod
    def capture(cls) -> WorkflowIdentity:
        """Consume the actual initial supervisor environment once, without an alternate override."""
        values: list[str] = []
        for key in Environment:
            value = os.environ.get(key)
            if not value or len(value) > 4096:
                raise ValueError(ERROR_WORKFLOW)
            values.append(value)
        identity = cls(*values)
        if (
            not identity.run_id.isascii()
            or not identity.run_id.isdecimal()
            or int(identity.run_id) <= 0
            or not identity.run_attempt.isascii()
            or not identity.run_attempt.isdecimal()
            or int(identity.run_attempt) <= 0
        ):
            raise ValueError(ERROR_WORKFLOW)
        return identity

    def record(self) -> JsonObject:
        """Keep only the declared provenance assertions, never the whole environment."""
        return {
            Environment.REPOSITORY: self.repository,
            Environment.WORKFLOW_REF: self.workflow_ref,
            Environment.RUN_ID: self.run_id,
            Environment.RUN_ATTEMPT: self.run_attempt,
        }


@dataclass(frozen=True)
class RunOwner:
    """Original supervisor-held ownership handles; no attach/adopt/restart constructor exists."""

    journal: ActionJournal
    workflow: WorkflowIdentity
    manifest_bytes: bytes

    @property
    def directory(self) -> Path:
        """The protected address helpers receive, not a replacement observation handle."""
        return STATE_ROOT / self.journal.binding.run_token

    def close(self) -> None:
        """Close both original evidence descriptors, without deleting retained run resources."""
        close_evidence_descriptors(self.journal.journal_fd, self.journal.directory_fd)

    @classmethod
    def create(
        cls,
        package: StaticPackage,
        candidate_commit: str,
        candidate_tree: str,
        realization_digest: str,
        deadline: Deadline,
        purpose: Purpose,
        *,
        realization_bytes: bytes,
        selected: frozenset[str],
    ) -> RunOwner:
        """Reserve fresh run ownership and its safe recovery prefix under the original supplied deadline."""
        if os.geteuid() != 0:
            raise ValueError(ERROR_OWNER)
        workflow = WorkflowIdentity.capture()
        for value, length in ((candidate_commit, 40), (candidate_tree, 40), (realization_digest, 64)):
            require_hex(value, length)
        controller = Controller.capture(os.getpid())
        nonce = secrets.token_bytes(NONCE_BYTES)
        token = hashlib.sha256(nonce + _encode(workflow.record())).hexdigest()[:32]
        binding = Binding(token, candidate_commit, candidate_tree, realization_digest, controller)
        binding_record = binding.record(deadline)
        inputs = (
            (STATIC_FILE, package.lock_bytes, STATIC_DIGEST),
            (RECIPE_FILE, package.recipe_bytes, RECIPE_DIGEST),
            (QUALIFICATION_FILE, package.qualification_bytes, QUALIFICATION_DIGEST),
            (REALIZATION_NAME, realization_bytes, realization_digest),
        )
        declarations: JsonObject = {}
        for name, blob, digest in inputs:
            if not blob or hashlib.sha256(blob).hexdigest() != digest:
                raise ValueError(ERROR_MANIFEST)
            declarations[name] = {Field.BYTES: len(blob), Field.SHA256: digest}
        if time.monotonic_ns() >= deadline.end_ns:
            raise TimeoutError(ERROR_OWNER)
        host = object_value(parse_object(package.recipe_bytes)[Key.HOST])
        parameters: dict[str, str] = {Parameter.RUN_TOKEN: token}
        record: JsonObject = {
            Key.BINDING: binding_record,
            Key.WORKFLOW: workflow.record(),
            Key.IMAGE_VERSION: workflow.image_version,
            Key.PURPOSE: purpose.value,
            Key.PARENT_UNIT: text(host, Key.PARENT_NAME).format_map(parameters),
            Key.GUEST_UNIT: text(host, Key.INSTANCE_NAME).format_map(parameters),
            Key.ROOTFS: text(host, Key.ROOTFS).format_map(parameters),
            Key.CREATED_NS: time.monotonic_ns(),
            Key.INPUTS: declarations,
            Key.SELECTED_SCENARIOS: list[JsonValue](sorted(selected)),
        }
        selection_argument(record)
        # This synchronous ownership step has no concurrent producer or await across the temporary umask.
        previous_umask = os.umask(PRIVATE_UMASK)
        journal: ActionJournal | None = None
        try:
            _require_state_root()
            journal = ActionJournal.create(STATE_ROOT, binding, deadline, package)
            for name, blob, _ in inputs:
                _write_private_file(journal.directory_fd, name, blob)
            record[Key.DIRECTORY_FD] = journal.directory_fd
            data = _encode(record)
            _write_private_file(journal.directory_fd, MANIFEST_NAME, data)
            controller.require_alive()
            if time.monotonic_ns() >= deadline.end_ns:
                raise TimeoutError(ERROR_OWNER)
            return cls(journal, workflow, data)
        except BaseException as error:
            error.add_note(ERROR_PREFIX.format(path=STATE_ROOT / token))
            if journal is not None:
                close_evidence_descriptors(journal.journal_fd, journal.directory_fd)
            raise
        finally:
            os.umask(previous_umask)


@dataclass(frozen=True)
class HelperOwner:
    """One direct helper child's inherited run ownership; this is not source/action admission."""

    journal: ActionJournal
    manifest_bytes: bytes
    inherited_directory_fd: int
    package: StaticPackage
    realization_bytes: bytes

    def close(self) -> None:
        """Close only this child process's descriptors; the supervisor retains its original handle."""
        close_evidence_descriptors(self.journal.journal_fd, self.journal.directory_fd, self.inherited_directory_fd)

    def require_original_parent(self) -> None:
        """Keep the direct native parent and original run handle bound before a helper effect."""
        controller = self.journal.binding.controller
        controller.require_alive()
        if os.geteuid() != 0 or controller.uid != 0 or os.getppid() != controller.pid:
            raise ValueError(ERROR_OWNER)
        parent_handle = Path(
            PARENT_DESCRIPTOR.format(pid=controller.pid, descriptor=self.inherited_directory_fd)
        ).stat()
        native = os.fstat(self.journal.directory_fd)
        if (parent_handle.st_dev, parent_handle.st_ino) != (native.st_dev, native.st_ino):
            raise ValueError(ERROR_OWNER)

    @classmethod
    def load(cls, manifest: Path, expected_digest: str, inherited_directory_fd: int, source_root: Path) -> HelperOwner:
        """Bind the protected header to the direct original supervisor and inherited directory capability."""
        require_hex(expected_digest, 64)
        if (
            os.geteuid() != 0
            or manifest.name != MANIFEST_NAME
            or manifest.parent.parent != STATE_ROOT
            or type(inherited_directory_fd) is not int
            or inherited_directory_fd <= 2
        ):
            raise ValueError(ERROR_OWNER)
        # Capture the actual inherited capability before any bootstrap open can reuse an absent descriptor number.
        _require_private_directory(inherited_directory_fd)
        original_native = os.fstat(inherited_directory_fd)
        token = manifest.parent.name
        require_hex(token, 32)
        root_fd = os.open(STATE_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        bootstrap_fd = -1
        descriptor = -1
        try:
            _require_private_directory(root_fd)
            bootstrap_fd = os.open(token, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
            _require_private_directory(bootstrap_fd)
            descriptor = os.open(MANIFEST_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=bootstrap_fd)
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != 0
                or stat.S_IMODE(before.st_mode) != FILE_MODE
                or before.st_nlink != 1
                or not 0 < before.st_size <= MANIFEST_LIMIT
            ):
                raise ValueError(ERROR_MANIFEST)
            data = os.pread(descriptor, MANIFEST_LIMIT + 1, 0)
            after = os.fstat(descriptor)
            if (
                len(data) != before.st_size
                or hashlib.sha256(data).hexdigest() != expected_digest
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise ValueError(ERROR_MANIFEST)
            record = parse_object(data)
            binding, deadline = _binding(record)
            if binding.run_token != token or binding.controller.pid != os.getppid() or binding.controller.uid != 0:
                raise ValueError(ERROR_OWNER)
            binding.controller.require_alive()
            inherited = positive_integer(record, Key.DIRECTORY_FD)
            if inherited != inherited_directory_fd:
                raise ValueError(ERROR_OWNER)
            _require_private_directory(inherited)
            inherited_native = os.fstat(inherited)
            bootstrap_native = os.fstat(bootstrap_fd)
            if (inherited_native.st_dev, inherited_native.st_ino) != (
                bootstrap_native.st_dev,
                bootstrap_native.st_ino,
            ) or (inherited_native.st_dev, inherited_native.st_ino) != (original_native.st_dev, original_native.st_ino):
                raise ValueError(ERROR_OWNER)
            linked = os.stat(MANIFEST_NAME, dir_fd=inherited, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError(ERROR_MANIFEST)
            inputs = _read_inputs(inherited, record, binding)
            package = StaticPackage(inputs[STATIC_FILE], inputs[RECIPE_FILE], inputs[QUALIFICATION_FILE])
            package.validate_source(source_root)
            _require_addresses(record, package, token)
        finally:
            close_evidence_descriptors(descriptor, bootstrap_fd, root_fd)
        journal = ActionJournal.attach_inherited(inherited, binding, deadline, package)
        try:
            context = cls(journal, data, inherited, package, inputs[REALIZATION_NAME])
            context.require_original_parent()
            return context
        except BaseException:
            close_evidence_descriptors(journal.journal_fd, journal.directory_fd)
            raise


def _binding(record: JsonObject) -> tuple[Binding, Deadline]:
    row = object_value(record[Key.BINDING])
    controller = Controller(
        positive_integer(row, JournalKey.CONTROLLER_PID),
        positive_integer(row, JournalKey.CONTROLLER_START),
        0,
        text(row, JournalKey.BOOT_ID),
    )
    deadline = Deadline(
        positive_integer(row, JournalKey.STARTED_NS),
        positive_integer(row, JournalKey.END_NS),
        positive_integer(row, JournalKey.RESERVE_NS),
    )
    binding = Binding(
        text(row, JournalKey.RUN_TOKEN),
        text(row, JournalKey.CANDIDATE_COMMIT),
        text(row, JournalKey.CANDIDATE_TREE),
        text(row, JournalKey.REALIZATION_DIGEST),
        controller,
    )
    if _encode(binding.record(deadline)) != _encode(row):
        raise ValueError(ERROR_MANIFEST)
    return binding, deadline


def _require_addresses(record: JsonObject, package: StaticPackage, token: str) -> None:
    Purpose(text(record, Key.PURPOSE))
    host = object_value(parse_object(package.recipe_bytes)[Key.HOST])
    parameters: dict[str, str] = {Parameter.RUN_TOKEN: token}
    for actual, declaration in (
        (Key.PARENT_UNIT, Key.PARENT_NAME),
        (Key.GUEST_UNIT, Key.INSTANCE_NAME),
        (Key.ROOTFS, Key.ROOTFS),
    ):
        if text(record, actual) != text(host, declaration).format_map(parameters):
            raise ValueError(ERROR_MANIFEST)
    selection_argument(record)


def selection_argument(record: JsonObject) -> str:
    """Carry the one protected full/selected choice into the frozen unit's declared substitution."""
    values = record.get(Key.SELECTED_SCENARIOS)
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value or not set(value) <= SCENARIO_CHARACTERS for value in values
    ):
        raise ValueError(ERROR_MANIFEST)
    names = [value for value in values if isinstance(value, str)]
    if names != sorted(set(names)):
        raise ValueError(ERROR_MANIFEST)
    return SELECTION_SEPARATOR.join(names)


def _require_private_directory(descriptor: int) -> None:
    native = os.fstat(descriptor)
    if not stat.S_ISDIR(native.st_mode) or native.st_uid != 0 or stat.S_IMODE(native.st_mode) != ROOT_MODE:
        raise ValueError(ERROR_OWNER)


def _read_inputs(directory_fd: int, record: JsonObject, binding: Binding) -> dict[str, bytes]:
    declarations = object_value(record[Key.INPUTS])
    result: dict[str, bytes] = {}
    for name, digest in (
        (STATIC_FILE, STATIC_DIGEST),
        (RECIPE_FILE, RECIPE_DIGEST),
        (QUALIFICATION_FILE, QUALIFICATION_DIGEST),
        (REALIZATION_NAME, binding.realization_digest),
    ):
        row = object_value(declarations[name])
        size = positive_integer(row, Field.BYTES)
        if text(row, Field.SHA256) != digest:
            raise ValueError(ERROR_INPUT.format(name=name))
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != 0
                or stat.S_IMODE(before.st_mode) != FILE_MODE
                or before.st_nlink != 1
                or before.st_size != size
            ):
                raise ValueError(ERROR_INPUT.format(name=name))
            data = os.pread(descriptor, size + 1, 0)
            after = os.fstat(descriptor)
            if (
                len(data) != size
                or hashlib.sha256(data).hexdigest() != digest
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise ValueError(ERROR_INPUT.format(name=name))
            result[name] = data
        finally:
            close_evidence_descriptors(descriptor)
    return result


def _encode(record: JsonObject) -> bytes:
    return json.dumps(record, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False).encode(UTF8)


def _require_state_root() -> None:
    parent_fd = os.open(STATE_ROOT.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    root_fd = -1
    try:
        try:
            os.mkdir(STATE_ROOT.name, mode=ROOT_MODE, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        root_fd = os.open(
            STATE_ROOT.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
        )
        native = os.fstat(root_fd)
        if native.st_uid != 0 or stat.S_IMODE(native.st_mode) != ROOT_MODE:
            raise ValueError(ERROR_OWNER)
    finally:
        close_evidence_descriptors(root_fd, parent_fd)


def _write_private_file(directory_fd: int, name: str, data: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        FILE_MODE,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(os.dup(descriptor), mode=EXCLUSIVE_BINARY) as handle:
            if handle.write(data) != len(data):
                raise OSError(ERROR_INPUT.format(name=name))
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory_fd)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, len(data) + 1) != data:
            raise OSError(ERROR_INPUT.format(name=name))
    finally:
        close_evidence_descriptors(descriptor)

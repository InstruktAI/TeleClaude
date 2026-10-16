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
    Deadline,
    JsonObject,
    Parameter,
    StaticPackage,
    object_value,
    parse_object,
    require_hex,
    text,
)
from tools.ci.enclosure_guest import Purpose, close_evidence_descriptors
from tools.ci.enclosure_journal import ActionJournal, Binding, Controller

STATE_ROOT: Final = Path("/var/lib/teleclaude-runtime-acceptance")
MANIFEST_NAME: Final = "manifest.json"
UTF8: Final = "utf-8"
JSON_SEPARATORS: Final = (",", ":")
EXCLUSIVE_BINARY: Final = "wb"
NONCE_BYTES: Final = 32
ROOT_MODE: Final = 0o700
FILE_MODE: Final = 0o600
PRIVATE_UMASK: Final = 0o077
ERROR_OWNER: Final = "outside ownership requires the original privileged controller and protected new run directory"
ERROR_WORKFLOW: Final = "the immutable hosted workflow/run attempt identity or provider image assertion is unavailable"
ERROR_MANIFEST: Final = "the initial protected run manifest could not be durably read back"
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
        }
        data = _encode(record)
        # This synchronous ownership step has no concurrent producer or await across the temporary umask.
        previous_umask = os.umask(PRIVATE_UMASK)
        journal: ActionJournal | None = None
        try:
            _require_state_root()
            journal = ActionJournal.create(STATE_ROOT, binding, deadline, package)
            _write_manifest(journal.directory_fd, data)
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


def _write_manifest(directory_fd: int, data: bytes) -> None:
    descriptor = os.open(
        MANIFEST_NAME,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        FILE_MODE,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(os.dup(descriptor), mode=EXCLUSIVE_BINARY) as handle:
            if handle.write(data) != len(data):
                raise OSError(ERROR_MANIFEST)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory_fd)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, len(data) + 1) != data:
            raise OSError(ERROR_MANIFEST)
    finally:
        close_evidence_descriptors(descriptor)

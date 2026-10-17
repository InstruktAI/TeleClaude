"""Protected setup/payload manifest handoff inside their existing journaled actions."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from typing import TYPE_CHECKING, Final

from tools.ci.enclosure_contract import (
    QUALIFICATION_DIGEST,
    RECIPE_DIGEST,
    STATIC_DIGEST,
    Action,
    AdmittedDeadline,
    Cutoff,
    Field,
    JsonObject,
    JsonValue,
    Phase,
    StaticPackage,
    object_value,
    parse_object,
    require_hex,
    text,
)
from tools.ci.enclosure_data import CONTROL_ROOT
from tools.ci.enclosure_guest import MANIFEST, SCHEMA_VERSION, Purpose, close_evidence_descriptors
from tools.ci.enclosure_guest import Key as GuestKey
from tools.ci.enclosure_journal import ActionResult, Outcome
from tools.ci.enclosure_owner import (
    FILE_MODE,
    MANIFEST_LIMIT,
    PARENT_DESCRIPTOR,
    REALIZATION_NAME,
    _read_inputs,
    _write_private_file,
)
from tools.ci.enclosure_owner import Key as OwnerKey

if TYPE_CHECKING:
    from tools.ci.enclosure_guest_binding import GuestBinding
    from tools.ci.enclosure_owner import HelperOwner, RunOwner

INPUT_NAME: Final = "guest-setup-manifest.json"
PAYLOAD_INPUT: Final = "guest-payload-manifest.json"
PAYLOAD_TEMPORARY: Final = "guest-payload-manifest.tmp"
MANIFEST_MODE: Final = 0o644
ERROR_MANIFEST: Final = "the protected guest manifest does not preserve its original admitted run/source/guest/cutoff"
DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
UTF8: Final = "utf-8"


def _encode(record: JsonObject) -> bytes:
    data = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(UTF8)
    if not data or len(data) > MANIFEST_LIMIT:
        raise ValueError(ERROR_MANIFEST)
    return data


def compose_setup_manifest(
    owner: RunOwner,
    package: StaticPackage,
    guest: GuestBinding,
    seal: ActionResult,
    selected: frozenset[str],
    deadline: AdmittedDeadline,
    qualification_vector: str | None,
) -> bytes:
    """Compose from protected source inputs and actual original guest facts, not caller identity assertions."""
    guest.require_original(deadline)
    if seal.status is not Outcome.SUCCEEDED or seal.evidence.get("phase") != Phase.ADMISSION_SEALED:
        raise ValueError(ERROR_MANIFEST)
    binding = owner.journal.binding
    if deadline.outer_end_ns != owner.journal.deadline.end_ns:
        raise ValueError(ERROR_MANIFEST)
    inputs = _read_inputs(owner.journal.directory_fd, parse_object(owner.manifest_bytes), binding)
    realization = parse_object(inputs[REALIZATION_NAME])
    source_files: JsonObject = {}
    for name, value in object_value(realization[GuestKey.SOURCE_FILES]).items():
        digest = text(object_value(value), Field.SHA256)
        require_hex(digest, 64)
        source_files[name] = digest
    purpose = Purpose(text(parse_object(owner.manifest_bytes), OwnerKey.PURPOSE))
    if purpose is Purpose.QUALIFICATION and (qualification_vector != "Q2" or deadline.vector_end_ns is None):
        raise ValueError(ERROR_MANIFEST)
    facts = guest.facts
    record: JsonObject = {
        GuestKey.SCHEMA_VERSION: SCHEMA_VERSION,
        GuestKey.RUN_TOKEN: binding.run_token,
        GuestKey.SOURCE_COMMIT: binding.candidate_commit,
        GuestKey.SOURCE_TREE: binding.candidate_tree,
        GuestKey.REALIZATION_SHA256: binding.realization_digest,
        GuestKey.STATIC_LOCK_SHA256: STATIC_DIGEST,
        GuestKey.RECIPE_SHA256: RECIPE_DIGEST,
        GuestKey.QUALIFICATION_SHA256: QUALIFICATION_DIGEST,
        GuestKey.ADMISSION_SEAL_SHA256: hashlib.sha256(_encode(seal.record(Action.MASK_GUEST))).hexdigest(),
        GuestKey.PURPOSE: purpose.value,
        GuestKey.QUALIFICATION_VECTOR: qualification_vector,
        GuestKey.GUEST_BOOT_ID: facts.guest_boot_id,
        GuestKey.UID_MAP: facts.uid_map,
        GuestKey.GID_MAP: facts.gid_map,
        GuestKey.PID_NAMESPACE: facts.pid_namespace,
        GuestKey.CGROUP_NAMESPACE: facts.cgroup_namespace,
        GuestKey.HOST_PID_NAMESPACE: facts.host_pid_namespace,
        GuestKey.HOST_CGROUP_NAMESPACE: facts.host_cgroup_namespace,
        GuestKey.SOURCE_FILES: source_files,
        GuestKey.SELECTED_SCENARIOS: list[JsonValue](sorted(selected)),
        Cutoff.OUTER_END_NS: deadline.outer_end_ns,
        Cutoff.VECTOR_END_NS: deadline.vector_end_ns,
        Cutoff.COMMAND_END_NS: deadline.command_end_ns,
    }
    if (
        hashlib.sha256(package.lock_bytes).hexdigest() != STATIC_DIGEST
        or hashlib.sha256(package.recipe_bytes).hexdigest() != RECIPE_DIGEST
        or hashlib.sha256(package.qualification_bytes).hexdigest() != QUALIFICATION_DIGEST
        or time.monotonic_ns() >= deadline.effective_end()
    ):
        raise ValueError(ERROR_MANIFEST)
    data = _encode(record)
    # This is a protected input in the existing run directory, not yet a guest mutation.
    _write_private_file(owner.journal.directory_fd, INPUT_NAME, data)
    return data


def narrow_setup_manifest(data: bytes, end_ns: int) -> bytes:
    """Only narrow the command cutoff to the helper's actual admitted end; preserve outer and vector identities."""
    record = parse_object(data)
    original = AdmittedDeadline.from_record(record, require_vector=False)
    if end_ns <= 0 or end_ns > original.effective_end():
        raise ValueError(ERROR_MANIFEST)
    record[Cutoff.COMMAND_END_NS] = end_ns
    return _encode(record)


def compose_payload_manifest(owner: RunOwner, setup: bytes, deadline: AdmittedDeadline) -> bytes:
    """Admit a new payload lifetime from the original run bounds; never extend the completed setup invocation."""
    record = parse_object(setup)
    if (
        record.get(GuestKey.PURPOSE) != Purpose.APPLICATION
        or record.get(GuestKey.RUN_TOKEN) != owner.journal.binding.run_token
        or deadline.outer_end_ns != owner.journal.deadline.end_ns
        or deadline.vector_end_ns is not None
    ):
        raise ValueError(ERROR_MANIFEST)
    work_end = min(deadline.effective_end(), deadline.outer_end_ns - owner.journal.deadline.reserve_ns)
    if time.monotonic_ns() >= work_end:
        raise TimeoutError(ERROR_MANIFEST)
    record[Cutoff.OUTER_END_NS] = deadline.outer_end_ns
    record[Cutoff.VECTOR_END_NS] = deadline.vector_end_ns
    record[Cutoff.COMMAND_END_NS] = deadline.command_end_ns
    record[GuestKey.PAYLOAD_END_NS] = work_end
    data = _encode(record)
    _write_private_file(owner.journal.directory_fd, PAYLOAD_INPUT, data)
    return data


def read_guest_input(
    owner: HelperOwner, root_fd: int, expected_digest: str, *, action: Action = Action.GUEST_SETUP
) -> bytes:
    """Read the parent's protected input and verify the actual inherited root capability."""
    require_hex(expected_digest, 64)
    if type(root_fd) is not int or root_fd <= 2 or root_fd == owner.inherited_directory_fd:
        raise ValueError(ERROR_MANIFEST)
    owner.require_original_parent()
    root = os.fstat(root_fd)
    parent_root = os.stat(PARENT_DESCRIPTOR.format(pid=owner.journal.binding.controller.pid, descriptor=root_fd))
    if not stat.S_ISDIR(root.st_mode) or (root.st_dev, root.st_ino, root.st_uid, root.st_gid) != (
        parent_root.st_dev,
        parent_root.st_ino,
        parent_root.st_uid,
        parent_root.st_gid,
    ):
        raise ValueError(ERROR_MANIFEST)
    names = {Action.GUEST_SETUP: INPUT_NAME, Action.START_PAYLOAD: PAYLOAD_INPUT, Action.POWEROFF: PAYLOAD_INPUT}
    if action not in names:
        raise ValueError(ERROR_MANIFEST)
    descriptor = os.open(names[action], READ_FLAGS, dir_fd=owner.journal.directory_fd)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) != FILE_MODE
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
        binding = owner.journal.binding
        if (
            record.get(GuestKey.RUN_TOKEN) != binding.run_token
            or record.get(GuestKey.SOURCE_COMMIT) != binding.candidate_commit
            or record.get(GuestKey.SOURCE_TREE) != binding.candidate_tree
            or record.get(GuestKey.REALIZATION_SHA256) != binding.realization_digest
            or record.get(GuestKey.PURPOSE) != parse_object(owner.manifest_bytes)[OwnerKey.PURPOSE]
            or record.get(GuestKey.STATIC_LOCK_SHA256) != STATIC_DIGEST
            or record.get(GuestKey.RECIPE_SHA256) != RECIPE_DIGEST
            or record.get(GuestKey.QUALIFICATION_SHA256) != QUALIFICATION_DIGEST
        ):
            raise ValueError(ERROR_MANIFEST)
        return data
    finally:
        close_evidence_descriptors(descriptor)


def publish_guest_manifest(
    owner: HelperOwner, root_fd: int, data: bytes, end_ns: int, *, previous_digest: str | None = None
) -> bytes:
    """Publish initial setup or replace its exact completed manifest inside the next admitted payload intent."""
    owner.require_original_parent()
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_MANIFEST)
    narrowed = narrow_setup_manifest(data, end_ns) if previous_digest is None else data
    if previous_digest is not None:
        require_hex(previous_digest, 64)
    root = os.fstat(root_fd)
    directory_fd = os.dup(root_fd)
    descriptor = -1
    try:
        for component in CONTROL_ROOT.parts:
            child = os.open(component, DIRECTORY_FLAGS, dir_fd=directory_fd)
            previous, directory_fd = directory_fd, child
            close_evidence_descriptors(previous)
            metadata = os.fstat(directory_fd)
            if metadata.st_uid != root.st_uid or (
                metadata.st_mode & 0o022 and not (component == CONTROL_ROOT.name and metadata.st_mode & stat.S_ISVTX)
            ):
                raise ValueError(ERROR_MANIFEST)
        if time.monotonic_ns() >= end_ns:
            raise TimeoutError(ERROR_MANIFEST)
        if previous_digest is not None:
            existing = os.open(MANIFEST.name, READ_FLAGS, dir_fd=directory_fd)
            try:
                before = os.fstat(existing)
                old = os.pread(existing, MANIFEST_LIMIT + 1, 0)
                after = os.fstat(existing)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != root.st_uid
                    or before.st_mode & 0o022
                    or not 0 < len(old) <= MANIFEST_LIMIT
                    or len(old) != before.st_size
                    or hashlib.sha256(old).hexdigest() != previous_digest
                    or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ValueError(ERROR_MANIFEST)
            finally:
                close_evidence_descriptors(existing)
        descriptor = os.open(
            MANIFEST.name if previous_digest is None else PAYLOAD_TEMPORARY,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            MANIFEST_MODE,
            dir_fd=directory_fd,
        )
        os.fchown(descriptor, root.st_uid, root.st_gid)
        os.fchmod(descriptor, MANIFEST_MODE)
        with os.fdopen(os.dup(descriptor), "wb") as handle:
            if handle.write(narrowed) != len(narrowed):
                raise OSError(ERROR_MANIFEST)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory_fd)
        if os.pread(descriptor, len(narrowed) + 1, 0) != narrowed or time.monotonic_ns() >= end_ns:
            raise ValueError(ERROR_MANIFEST)
        if previous_digest is not None:
            os.replace(PAYLOAD_TEMPORARY, MANIFEST.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
            actual = os.open(MANIFEST.name, READ_FLAGS, dir_fd=directory_fd)
            try:
                if os.pread(actual, len(narrowed) + 1, 0) != narrowed or time.monotonic_ns() >= end_ns:
                    raise ValueError(ERROR_MANIFEST)
            finally:
                close_evidence_descriptors(actual)
        return narrowed
    finally:
        close_evidence_descriptors(descriptor, directory_fd)

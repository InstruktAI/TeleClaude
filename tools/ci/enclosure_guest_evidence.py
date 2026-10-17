"""Named evidence reads through the original guest mount view, with setup semantics kept separate."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from tools.ci.enclosure_contract import (
    NANOSECONDS,
    AdmittedDeadline,
    Field,
    JsonObject,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    require_hex,
    text,
)
from tools.ci.enclosure_data import CONTROL_ROOT
from tools.ci.enclosure_guest import JOURNAL as POWEROFF_JOURNAL
from tools.ci.enclosure_guest import Key as GuestKey
from tools.ci.enclosure_guest import Purpose, Record, Role, close_evidence_descriptors
from tools.ci.enclosure_native import INVENTORY_ARGUMENTS, READ_LIMIT
from tools.ci.enclosure_setup import (
    COREPACK,
    PNPM,
    PRETTIER,
    SETUP_JOURNAL,
    GuestManagerFacts,
    GuestOSFacts,
    setup_admission_binding,
)
from tools.ci.enclosure_setup import Key as SetupKey

ERROR_PROTECTION: Final = "the named guest evidence is not protected in the admitted mount view"
ERROR_READ: Final = "the guest evidence read is incomplete, changed or outside the original allowance"
DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
SHARED_WRITE: Final = stat.S_IWGRP | stat.S_IWOTH
UID_UNMAPPED: Final = 2**32 - 1
ERROR_SETUP: Final = "the captured guest setup journal does not establish the admitted setup result"


class FactKey(StrEnum):
    """Fields of the existing setup facts, not additional guest observations."""

    INVENTORY_SHA256 = "inventory_sha256"
    BOOTSTRAP_ARCHIVE_DIGESTS = "bootstrap_archive_digests"
    COREPACK_METADATA_SHA256 = "corepack_metadata_sha256"
    SYSTEM_MANAGER = "system_manager"
    USER_MANAGER = "user_manager"
    POLICY_REMOVED = "package_service_policy_removed"
    START_TICKS = "start_ticks"
    CGROUP = "cgroup"
    OBSERVED_NS = "observed_ns"


class EvidenceLeaf(StrEnum):
    """Only existing named setup, automatic cleanup and report artifacts may be read here."""

    SETUP = SETUP_JOURNAL
    POWEROFF = POWEROFF_JOURNAL
    REPORT = "report.json"


@dataclass(frozen=True)
class JournalFileIdentity:
    """Native leaf metadata in the supplied mount view, including change timestamps."""

    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> JournalFileIdentity:
        """Keep the native metadata without translating ownership a second time."""
        return cls(
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_uid,
            value.st_gid,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )


@dataclass(frozen=True)
class GuestFileRead:
    """Raw evidence survives independently of its completeness or later semantic validation."""

    data: bytes
    sha256: str
    before: JournalFileIdentity
    after: JournalFileIdentity | None
    named_leaf: JournalFileIdentity | None
    read_error: OSError | None
    started_ns: int
    finished_ns: int
    end_ns: int
    read_limit: int = READ_LIMIT

    def require_complete(self) -> None:
        """Reject partial, replaced, changed or late evidence before any setup-phase claim."""
        if (
            self.read_error is not None
            or self.before != self.after
            or self.after != self.named_leaf
            or not 0 < len(self.data) <= self.read_limit
            or len(self.data) != self.before.size
            or self.finished_ns >= self.end_ns
        ):
            raise ValueError(ERROR_READ)


@dataclass(frozen=True)
class GuestSetupEvidence:
    """Validated setup evidence; original outside identity/continuity and phase admission remain separate."""

    journal: GuestFileRead
    manifest_sha256: str
    unit_end_ns: int
    completed_ns: int
    command_count: int
    facts: GuestOSFacts


def _digest(record: JsonObject, key: str) -> str:
    value = text(record, key)
    require_hex(value, 64)
    return value


def _manager_facts(
    record: JsonObject, admission: JsonObject, uid: int, first_ns: int, completed_ns: int
) -> GuestManagerFacts:
    pid = positive_integer(record, GuestKey.PID)
    observed = positive_integer(record, FactKey.OBSERVED_NS)
    if (
        type(record.get(SetupKey.UID)) is not int
        or record[SetupKey.UID] != uid
        or (uid == 0 and pid != 1)
        or (uid != 0 and pid <= 1)
        or text(record, GuestKey.PID_NAMESPACE) != text(admission, GuestKey.PID_NAMESPACE)
        or text(record, GuestKey.CGROUP_NAMESPACE) != text(admission, GuestKey.CGROUP_NAMESPACE)
        or not first_ns <= observed <= completed_ns
    ):
        raise ValueError(ERROR_SETUP)
    return GuestManagerFacts(
        uid,
        pid,
        positive_integer(record, FactKey.START_TICKS),
        text(record, GuestKey.PID_NAMESPACE),
        text(record, GuestKey.CGROUP_NAMESPACE),
        text(record, FactKey.CGROUP),
        observed,
    )


def _setup_facts(
    record: JsonObject,
    admission: JsonObject,
    package: StaticPackage,
    first_ns: int,
    completed_ns: int,
) -> GuestOSFacts:
    recipe = parse_object(package.recipe_bytes)
    account = object_value(object_value(recipe[SetupKey.GUEST])[SetupKey.ACCOUNT])
    uid, gid = positive_integer(account, SetupKey.UID), positive_integer(account, SetupKey.GID)
    policy_removed = Purpose(text(admission, GuestKey.PURPOSE)) is Purpose.APPLICATION
    if (
        text(record, SetupKey.ACCOUNT) != text(account, SetupKey.NAME)
        or positive_integer(record, SetupKey.UID) != uid
        or positive_integer(record, SetupKey.GID) != gid
        or text(record, SetupKey.HOME) != text(account, SetupKey.HOME)
        or text(record, SetupKey.SHELL) != text(account, SetupKey.SHELL)
        or record.get(FactKey.POLICY_REMOVED) is not policy_removed
    ):
        raise ValueError(ERROR_SETUP)
    tools = parse_object(package.lock_bytes)[SetupKey.NPM_TOOLS]
    if not isinstance(tools, list):
        raise ValueError(ERROR_SETUP)
    digests: dict[str, str] = {}
    for value in tools:
        tool = object_value(value)
        name = text(tool, SetupKey.PACKAGE)
        if name in digests:
            raise ValueError(ERROR_SETUP)
        digests[name] = _digest(tool, Field.SHA256)
    bootstrap = tuple(digests[name] for name in (COREPACK, PRETTIER, PNPM))
    if record.get(FactKey.BOOTSTRAP_ARCHIVE_DIGESTS) != list(bootstrap):
        raise ValueError(ERROR_SETUP)
    return GuestOSFacts(
        _digest(record, FactKey.INVENTORY_SHA256),
        text(record, SetupKey.ACCOUNT),
        uid,
        gid,
        text(record, SetupKey.HOME),
        text(record, SetupKey.SHELL),
        bootstrap,
        _digest(record, FactKey.COREPACK_METADATA_SHA256),
        _manager_facts(object_value(record[FactKey.SYSTEM_MANAGER]), admission, 0, first_ns, completed_ns),
        _manager_facts(object_value(record[FactKey.USER_MANAGER]), admission, uid, first_ns, completed_ns),
        policy_removed,
    )


def _commands(rows: list[JsonObject], unit_end: int, cap: int) -> tuple[int, str]:
    """Consume each original one-shot intent/start/outcome, without replaying the setup command recipe."""
    if not rows or len(rows) % 3:
        raise ValueError(ERROR_SETUP)
    inventory = None
    for index in range(0, len(rows), 3):
        intent, started, outcome = rows[index : index + 3]
        sequence = index // 3 + 1
        for row, expected in zip(
            (intent, started, outcome), (Record.INTENT, Record.STARTED, Record.ACKNOWLEDGED), strict=True
        ):
            if (
                row.get(SetupKey.SCOPE) != SetupKey.COMMAND
                or row.get(GuestKey.RECORD) != expected
                or positive_integer(row, SetupKey.SEQUENCE) != sequence
            ):
                raise ValueError(ERROR_SETUP)
        argv = intent.get(GuestKey.COMMAND)
        if not isinstance(argv, list) or not argv or any(not isinstance(part, str) or not part for part in argv):
            raise ValueError(ERROR_SETUP)
        requested = positive_integer(intent, SetupKey.REQUESTED_COMMAND_END_NS)
        end = positive_integer(intent, SetupKey.COMMAND_END_NS)
        timestamp = positive_integer(intent, GuestKey.MONOTONIC_NS)
        if (
            end != min(requested, unit_end)
            or not timestamp < end <= timestamp + cap * NANOSECONDS
            or positive_integer(outcome, GuestKey.MONOTONIC_NS) >= end
            or type(outcome.get(GuestKey.EXIT_STATUS)) is not int
            or outcome[GuestKey.EXIT_STATUS] != 0
            or outcome.get(GuestKey.ERROR_CLASS) is not None
            or type(outcome.get(SetupKey.STDOUT_COMPLETE)) is not bool
        ):
            raise ValueError(ERROR_SETUP)
        positive_integer(started, GuestKey.PID)
        if outcome[SetupKey.STDOUT_COMPLETE]:
            _digest(outcome, SetupKey.STDOUT_SHA256)
        elif outcome.get(SetupKey.STDOUT_SHA256) is not None:
            raise ValueError(ERROR_SETUP)
        if argv == list(INVENTORY_ARGUMENTS):
            if inventory is not None or outcome[SetupKey.STDOUT_COMPLETE] is not True:
                raise ValueError(ERROR_SETUP)
            inventory = _digest(outcome, SetupKey.STDOUT_SHA256)
    if inventory is None:
        raise ValueError(ERROR_SETUP)
    return len(rows) // 3, inventory


def validate_setup_journal(read: GuestFileRead, admitted_manifest: bytes, package: StaticPackage) -> GuestSetupEvidence:
    """Validate captured setup semantics against the caller's admitted manifest; perform no guest action.

    This does not admit a manifest, root descriptor or manager. The phase caller
    must already own those original bindings and still check their continuity.
    Invalid data remains in the caller's separate GuestFileRead on failure.
    """
    read.require_complete()
    _before_cutoff(read.end_ns)
    if not read.data.endswith(b"\n"):
        raise ValueError(ERROR_SETUP)
    rows = [parse_object(line) for line in read.data.split(b"\n")[:-1]]
    if len(rows) < 5:
        raise ValueError(ERROR_SETUP)
    admission = parse_object(admitted_manifest)
    purpose = Purpose(text(admission, GuestKey.PURPOSE))
    if purpose is Purpose.QUALIFICATION and admission.get(GuestKey.QUALIFICATION_VECTOR) != "Q2":
        raise ValueError(ERROR_SETUP)
    first, terminal = rows[0], rows[-1]
    manifest_digest = hashlib.sha256(admitted_manifest).hexdigest()
    if (
        first.get(SetupKey.SCOPE) != SetupKey.ADMISSION
        or first.get(GuestKey.RECORD) != Record.INTENT
        or first.get(SetupKey.ROLE) != Role.GUEST_SETUP
        or first.get(GuestKey.MANIFEST_SHA256) != manifest_digest
        or first.get(SetupKey.ADMISSION) != setup_admission_binding(admission)
        or terminal.get(SetupKey.SCOPE) != SetupKey.SETUP
        or terminal.get(GuestKey.RECORD) != Record.ACKNOWLEDGED
        or GuestKey.ERROR_CLASS not in terminal
        or terminal.get(GuestKey.ERROR_CLASS) is not None
    ):
        raise ValueError(ERROR_SETUP)
    original = AdmittedDeadline.from_record(admission, require_vector=purpose is Purpose.QUALIFICATION)
    budget = object_value(parse_object(package.recipe_bytes)[Field.BUDGET_SECONDS])
    first_ns = positive_integer(first, GuestKey.MONOTONIC_NS)
    unit_end = positive_integer(first, SetupKey.UNIT_END_NS)
    if (
        not first_ns
        < unit_end
        <= min(
            original.effective_end(),
            first_ns + positive_integer(budget, Field.GUEST_BOOT_OR_CONFIGURATION_MAX) * NANOSECONDS,
        )
    ):
        raise ValueError(ERROR_SETUP)
    previous = first_ns
    for row in rows:
        observed = positive_integer(row, GuestKey.MONOTONIC_NS)
        if not previous <= observed < unit_end or observed > read.finished_ns:
            raise ValueError(ERROR_SETUP)
        previous = observed
    count, inventory = _commands(rows[1:-1], unit_end, positive_integer(budget, Field.NORMAL_COMMAND_MAX))
    facts = _setup_facts(object_value(terminal[SetupKey.FACTS]), admission, package, first_ns, previous)
    if facts.inventory_sha256 != inventory:
        raise ValueError(ERROR_SETUP)
    _before_cutoff(min(read.end_ns, original.effective_end()))
    return GuestSetupEvidence(read, manifest_digest, unit_end, previous, count, facts)


def _protected_directory(descriptor: int, root_uid: int, *, control: bool) -> None:
    metadata = os.fstat(descriptor)
    shared_write = metadata.st_mode & SHARED_WRITE
    sticky_control = control and bool(metadata.st_mode & stat.S_ISVTX)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != root_uid or (shared_write and not sticky_control):
        raise ValueError(ERROR_PROTECTION)


def _before_cutoff(end_ns: int) -> None:
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_READ)


def read_guest_evidence(
    guest_root_fd: int,
    outside_guest_root_uid: int,
    outside_file_uid: int,
    leaf: EvidenceLeaf,
    deadline: AdmittedDeadline,
) -> GuestFileRead:
    """Read only a declared evidence leaf; the caller retains guest-leader/mount/namespace admission.

    The supplied descriptor must refer to that admitted guest's root mount view.
    A host image-directory descriptor and a guessed UID-map offset do not establish
    this boundary: native stat ownership also depends on the mount's idmapping.
    No caller descriptor is closed or reopened by path, and this read grants no phase.
    """
    if (
        type(outside_guest_root_uid) is not int
        or not 0 < outside_guest_root_uid < UID_UNMAPPED
        or type(outside_file_uid) is not int
        or not 0 < outside_file_uid < UID_UNMAPPED
        or type(leaf) is not EvidenceLeaf
    ):
        raise ValueError(ERROR_PROTECTION)
    started = time.monotonic_ns()
    end = deadline.effective_end()
    _before_cutoff(end)
    directory_fd = os.dup(guest_root_fd)
    leaf_fd = -1
    try:
        _protected_directory(directory_fd, outside_guest_root_uid, control=False)
        for component in CONTROL_ROOT.parts:
            _before_cutoff(end)
            child_fd = os.open(component, DIRECTORY_FLAGS, dir_fd=directory_fd)
            previous_fd, directory_fd = directory_fd, child_fd
            close_evidence_descriptors(previous_fd)
            _protected_directory(directory_fd, outside_guest_root_uid, control=component == CONTROL_ROOT.name)
        _before_cutoff(end)
        leaf_fd = os.open(leaf, FILE_FLAGS, dir_fd=directory_fd)
        before = JournalFileIdentity.from_stat(os.fstat(leaf_fd))
        if not stat.S_ISREG(before.mode) or before.uid != outside_file_uid or before.mode & SHARED_WRITE:
            raise ValueError(ERROR_PROTECTION)
        _before_cutoff(end)
        # Journals retain the existing native limit; the report has its writer's actual finite size,
        # not a new acceptance size limit imposed by this readback consumer.
        read_limit = before.size if leaf is EvidenceLeaf.REPORT else READ_LIMIT
        data = os.pread(leaf_fd, read_limit + 1, 0)
        after = None
        named_leaf = None
        read_error = None
        try:
            after = JournalFileIdentity.from_stat(os.fstat(leaf_fd))
            named_leaf = JournalFileIdentity.from_stat(os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False))
        except OSError as error:
            read_error = error
        return GuestFileRead(
            data,
            hashlib.sha256(data).hexdigest(),
            before,
            after,
            named_leaf,
            read_error,
            started,
            time.monotonic_ns(),
            end,
            read_limit,
        )
    finally:
        close_evidence_descriptors(leaf_fd, directory_fd)

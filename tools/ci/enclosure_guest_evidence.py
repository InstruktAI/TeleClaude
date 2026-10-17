"""Bounded setup-journal read through the caller's admitted guest mount view."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import dataclass
from typing import Final

from tools.ci.enclosure_contract import AdmittedDeadline
from tools.ci.enclosure_data import CONTROL_ROOT
from tools.ci.enclosure_guest import close_evidence_descriptors
from tools.ci.enclosure_native import READ_LIMIT
from tools.ci.enclosure_setup import SETUP_JOURNAL

ERROR_PROTECTION: Final = "the named guest setup evidence is not protected in the admitted mount view"
ERROR_READ: Final = "the guest setup journal read is incomplete, changed or outside the original allowance"
DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
SHARED_WRITE: Final = stat.S_IWGRP | stat.S_IWOTH
UID_UNMAPPED: Final = 2**32 - 1


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
class SetupJournalRead:
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

    def require_complete(self) -> None:
        """Reject partial, replaced, changed or late evidence before any setup-phase claim."""
        if (
            self.read_error is not None
            or self.before != self.after
            or self.after != self.named_leaf
            or not 0 < len(self.data) <= READ_LIMIT
            or len(self.data) != self.before.size
            or self.finished_ns >= self.end_ns
        ):
            raise ValueError(ERROR_READ)


def _protected_directory(descriptor: int, root_uid: int, *, control: bool) -> None:
    metadata = os.fstat(descriptor)
    shared_write = metadata.st_mode & SHARED_WRITE
    sticky_control = control and bool(metadata.st_mode & stat.S_ISVTX)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != root_uid or (shared_write and not sticky_control):
        raise ValueError(ERROR_PROTECTION)


def _before_cutoff(end_ns: int) -> None:
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_READ)


def read_setup_journal(guest_root_fd: int, outside_guest_root_uid: int, deadline: AdmittedDeadline) -> SetupJournalRead:
    """Read only the fixed setup leaf; the caller retains guest-leader/mount/namespace admission.

    The supplied descriptor must refer to that admitted guest's root mount view.
    A host image-directory descriptor and a guessed UID-map offset do not establish
    this boundary: native stat ownership also depends on the mount's idmapping.
    No caller descriptor is closed or reopened by path, and this read grants no phase.
    """
    if type(outside_guest_root_uid) is not int or not 0 < outside_guest_root_uid < UID_UNMAPPED:
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
        leaf_fd = os.open(SETUP_JOURNAL, FILE_FLAGS, dir_fd=directory_fd)
        before = JournalFileIdentity.from_stat(os.fstat(leaf_fd))
        if not stat.S_ISREG(before.mode) or before.uid != outside_guest_root_uid or before.mode & SHARED_WRITE:
            raise ValueError(ERROR_PROTECTION)
        _before_cutoff(end)
        data = os.pread(leaf_fd, READ_LIMIT + 1, 0)
        after = None
        named_leaf = None
        read_error = None
        try:
            after = JournalFileIdentity.from_stat(os.fstat(leaf_fd))
            named_leaf = JournalFileIdentity.from_stat(
                os.stat(SETUP_JOURNAL, dir_fd=directory_fd, follow_symlinks=False)
            )
        except OSError as error:
            read_error = error
        return SetupJournalRead(
            data,
            hashlib.sha256(data).hexdigest(),
            before,
            after,
            named_leaf,
            read_error,
            started,
            time.monotonic_ns(),
            end,
        )
    finally:
        close_evidence_descriptors(leaf_fd, directory_fd)

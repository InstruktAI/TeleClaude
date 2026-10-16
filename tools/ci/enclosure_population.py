"""Original-descriptor population observations for the acceptance enclosure.

This primitive supplies native observations, not the complete P4 conjunction.
Manager, admission, invocation, shutdown and evidence ownership are separate facts.
"""

from __future__ import annotations

import ctypes
import errno
import os
import struct
import sys
import threading
import time
from dataclasses import dataclass
from enum import IntFlag, StrEnum
from pathlib import Path
from typing import Final

LINUX: Final = "linux"
CGROUP_ROOT: Final = Path("/sys/fs/cgroup")
EVENTS_FILE: Final = "cgroup.events"
FD_PATH: Final = "/proc/self/fd/{descriptor}"
PATH_SEPARATOR: Final = "/"
DOT_COMPONENTS: Final = frozenset({"", ".", ".."})
POPULATED: Final = b"populated"
ZERO: Final = b"0"
ONE: Final = b"1"
NEWLINE: Final = b"\n"
EVENT_HEADER: Final = struct.Struct("=iIII")
EVENT_BUFFER_BYTES: Final = 64 * 1024
POPULATION_BYTES: Final = 4096
LINUX_O_PATH: Final = 0o10000000
ERROR_UNSUPPORTED: Final = "original-object population observation requires the reviewed Linux substrate"
ERROR_PATH: Final = "the manager ControlGroup must name a non-root absolute cgroup without traversal"
ERROR_NATIVE: Final = "native original-object watch could not be established"
ERROR_POPULATION: Final = "the original cgroup.events population record is invalid"


class NativeMask(IntFlag):
    """Linux inotify ABI bits used by the reviewed native monitoring recipe."""

    MODIFY = 0x00000002
    DELETE_SELF = 0x00000400
    MOVE_SELF = 0x00000800
    UNMOUNT = 0x00002000
    QUEUE_OVERFLOW = 0x00004000
    IGNORED = 0x00008000


class Invalidation(StrEnum):
    """Sticky observation losses; a later empty read never removes a cause."""

    REMOVED = "removed"
    MOVED = "moved"
    UNMOUNTED = "unmounted"
    WATCH_DROPPED = "watch_dropped"
    OVERFLOW = "overflow"
    MALFORMED_STREAM = "malformed_stream"
    UNKNOWN_WATCH = "unknown_watch"
    READ_FAILED = "read_failed"
    DEAD_HANDLE = "dead_handle"
    INVALID_POPULATION = "invalid_population"
    DEADLINE_EXPIRED = "deadline_expired"
    MONITOR_CLOSED = "monitor_closed"
    BUS_DISCONNECTED = "bus_disconnected"
    MANAGER_CHANGED = "manager_changed"
    PARENT_DEACTIVATED = "parent_deactivated"
    PARENT_REPLACED = "parent_replaced"
    INVOCATION_CHANGED = "invocation_changed"
    UNKNOWN_ACTIVATOR = "unknown_activator"


INVALIDATING_MASKS: Final = {
    NativeMask.DELETE_SELF: Invalidation.REMOVED,
    NativeMask.MOVE_SELF: Invalidation.MOVED,
    NativeMask.UNMOUNT: Invalidation.UNMOUNTED,
    NativeMask.IGNORED: Invalidation.WATCH_DROPPED,
    NativeMask.QUEUE_OVERFLOW: Invalidation.OVERFLOW,
}
WATCH_MASK: Final = (
    NativeMask.MODIFY | NativeMask.DELETE_SELF | NativeMask.MOVE_SELF | NativeMask.UNMOUNT | NativeMask.IGNORED
)


@dataclass(frozen=True)
class Fault:
    """The first native fact for one irreversible invalidation cause."""

    cause: Invalidation
    observed_ns: int
    sequence: int
    error_number: int | None = None
    native_mask: int | None = None
    watch_descriptor: int | None = None


@dataclass(frozen=True)
class PopulationRead:
    """One bounded raw read bracketed by notification drains; no complete P4 verdict."""

    raw: bytes
    populated: bool | None
    read_started_ns: int
    read_finished_ns: int
    last_notification_sequence: int
    faults: tuple[Fault, ...]


class PopulationObserver:
    """Hold original directory/event descriptors and one non-reconnecting native queue."""

    def __init__(self, control_group: str):
        if sys.platform != LINUX:
            raise NotImplementedError(ERROR_UNSUPPORTED)
        parts = control_group.split(PATH_SEPARATOR)
        if (
            not control_group.startswith(PATH_SEPARATOR)
            or len(parts) < 2
            or any(part in DOT_COMPONENTS for part in parts[1:])
        ):
            raise ValueError(ERROR_PATH)
        self._lock = threading.RLock()
        self._faults: dict[Invalidation, Fault] = {}
        self._sequence = 0
        self._closed = False
        self._directory_fd = -1
        self._events_fd = -1
        self._notify_fd = -1
        self._watches: frozenset[int] = frozenset()
        try:
            self._directory_fd = _open_original(parts[1:])
            self._events_fd = os.open(
                EVENTS_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._directory_fd
            )
            # Python exposes no native inotify API; the reviewed recipe uses libc directly.
            library = ctypes.CDLL(None, use_errno=True)
            library.inotify_init1.argtypes = [ctypes.c_int]
            library.inotify_init1.restype = ctypes.c_int
            library.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            library.inotify_add_watch.restype = ctypes.c_int
            self._notify_fd = int(library.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
            if self._notify_fd < 0:
                raise OSError(ctypes.get_errno(), ERROR_NATIVE)
            watches: set[int] = set()
            for descriptor in (self._directory_fd, self._events_fd):
                anchored = os.fsencode(FD_PATH.format(descriptor=descriptor))
                watch = int(library.inotify_add_watch(self._notify_fd, anchored, int(WATCH_MASK)))
                if watch < 0 or watch in watches:
                    raise OSError(ctypes.get_errno(), ERROR_NATIVE)
                watches.add(watch)
            self._watches = frozenset(watches)
        except BaseException:
            self.close()
            raise

    def invalidate(
        self,
        cause: Invalidation,
        error_number: int | None = None,
        *,
        native_mask: int | None = None,
        watch_descriptor: int | None = None,
    ) -> None:
        """Retain the first fact for a cause, including manager facts supplied by its observer."""
        with self._lock:
            if cause not in self._faults:
                self._faults[cause] = Fault(
                    cause, time.monotonic_ns(), self._sequence, error_number, native_mask, watch_descriptor
                )

    def fileno(self) -> int:
        """Expose the original queue to the supervisor's native readiness loop."""
        return self._notify_fd

    def observe_notifications(self, deadline_ns: int) -> None:
        """Drain readiness notifications within the original supplied allowance."""
        with self._lock:
            self._drain(deadline_ns)

    def _drain(self, deadline_ns: int) -> None:
        while not self._closed:
            if time.monotonic_ns() >= deadline_ns:
                self.invalidate(Invalidation.DEADLINE_EXPIRED)
                return
            try:
                data = os.read(self._notify_fd, EVENT_BUFFER_BYTES)
            except BlockingIOError:
                return
            except OSError as error:
                self.invalidate(
                    Invalidation.DEAD_HANDLE if error.errno == errno.EBADF else Invalidation.READ_FAILED, error.errno
                )
                return
            if not data:
                self.invalidate(Invalidation.READ_FAILED)
                return
            offset = 0
            while offset < len(data):
                if offset + EVENT_HEADER.size > len(data):
                    self.invalidate(Invalidation.MALFORMED_STREAM)
                    return
                descriptor, mask, _cookie, name_length = EVENT_HEADER.unpack_from(data, offset)
                offset += EVENT_HEADER.size + name_length
                self._sequence += 1
                if offset > len(data):
                    self.invalidate(Invalidation.MALFORMED_STREAM)
                    return
                if descriptor not in self._watches and not (mask & NativeMask.QUEUE_OVERFLOW):
                    self.invalidate(Invalidation.UNKNOWN_WATCH, native_mask=mask, watch_descriptor=descriptor)
                for flag, cause in INVALIDATING_MASKS.items():
                    if mask & flag:
                        self.invalidate(cause, native_mask=mask, watch_descriptor=descriptor)

    def sample(self, deadline_ns: int) -> PopulationRead:
        """Use original descriptors only; all faults survive subsequent readable empty data."""
        with self._lock:
            started = time.monotonic_ns()
            self._drain(deadline_ns)
            raw = b""
            populated: bool | None = None
            if self._closed:
                self.invalidate(Invalidation.MONITOR_CLOSED)
            elif time.monotonic_ns() >= deadline_ns:
                self.invalidate(Invalidation.DEADLINE_EXPIRED)
            else:
                try:
                    os.fstat(self._directory_fd)
                    raw = os.pread(self._events_fd, POPULATION_BYTES + 1, 0)
                    populated = _population(raw)
                except OSError as error:
                    self.invalidate(
                        Invalidation.DEAD_HANDLE if error.errno == errno.EBADF else Invalidation.READ_FAILED,
                        error.errno,
                    )
                except ValueError:
                    self.invalidate(Invalidation.INVALID_POPULATION)
                self._drain(deadline_ns)
            if time.monotonic_ns() >= deadline_ns:
                self.invalidate(Invalidation.DEADLINE_EXPIRED)
            return PopulationRead(
                raw, populated, started, time.monotonic_ns(), self._sequence, tuple(self._faults.values())
            )

    def close(self) -> None:
        """End observation explicitly; any later read carries irreversible closure evidence."""
        with self._lock:
            self.invalidate(Invalidation.MONITOR_CLOSED)
            self._closed = True
            for descriptor in (self._notify_fd, self._events_fd, self._directory_fd):
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError as error:
                        self.invalidate(Invalidation.READ_FAILED, error.errno)
            self._notify_fd = self._events_fd = self._directory_fd = -1


def _open_original(parts: list[str]) -> int:
    descriptor = os.open(CGROUP_ROOT, LINUX_O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for part in parts:
            child = os.open(part, LINUX_O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _population(raw: bytes) -> bool:
    if not raw or len(raw) > POPULATION_BYTES or not raw.endswith(NEWLINE):
        raise ValueError(ERROR_POPULATION)
    fields: dict[bytes, bytes] = {}
    for line in raw.splitlines():
        pair = line.split()
        if len(pair) != 2 or pair[0] in fields or not pair[1].isdigit():
            raise ValueError(ERROR_POPULATION)
        fields[pair[0]] = pair[1]
    if fields.get(POPULATED) not in (ZERO, ONE):
        raise ValueError(ERROR_POPULATION)
    return fields[POPULATED] == ONE

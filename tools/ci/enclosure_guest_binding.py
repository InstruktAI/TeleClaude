"""Outside admission of the actual registered guest leader and its original mount view."""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final
from uuid import UUID

from tools.ci.enclosure_contract import AdmittedDeadline, JsonObject, parse_object, text
from tools.ci.enclosure_guest import _nonidentity_map, close_evidence_descriptors
from tools.ci.enclosure_journal import PROC_START_INDEX, PROC_STAT_END, Controller, TerminalProcessState
from tools.ci.enclosure_manager import ACTIVE, MachineRead, Property, UnitRead
from tools.ci.enclosure_native import READ_LIMIT

ERROR_BINDING: Final = "the original guest leader, namespace, mapping or root mount view is unavailable or changed"
UTF8: Final = "utf-8"
DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
NAMESPACES: Final = ("pid", "cgroup", "mnt", "user")
ROOT_BOOT: Final = ("proc", "sys", "kernel", "random")
BOOT_FILE: Final = "boot_id"
UINT_MAX: Final = 2**32 - 1


def _before_cutoff(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_BINDING)


def _read(descriptor: int, name: str) -> str:
    native = os.open(name, READ_FLAGS, dir_fd=descriptor)
    with os.fdopen(native, "rb") as handle:
        data = handle.read(READ_LIMIT + 1)
    if not data or len(data) > READ_LIMIT:
        raise ValueError(ERROR_BINDING)
    return data.decode(UTF8)


def _root_id(raw: str) -> int:
    _nonidentity_map(raw)
    for line in raw.splitlines():
        inside, outside, count = (int(part) for part in line.split())
        if inside == 0 and 0 < outside < UINT_MAX and count > 0:
            return outside
    raise ValueError(ERROR_BINDING)


def _boot(root_fd: int) -> str:
    current = os.dup(root_fd)
    try:
        for component in ROOT_BOOT:
            child = os.open(component, DIRECTORY_FLAGS, dir_fd=current)
            previous, current = current, child
            close_evidence_descriptors(previous)
        value = _read(current, BOOT_FILE).strip()
        # The native kernel presentation is a UUID, not an arbitrary identity assertion.
        if str(UUID(value)) != value:
            raise ValueError(ERROR_BINDING)
        return value
    finally:
        close_evidence_descriptors(current)


@dataclass(frozen=True)
class GuestLeaderFacts:
    """Native outside facts; guest root ownership is observed through its actual mount view."""

    controller: Controller
    uid_map: str
    gid_map: str
    pid_namespace: str
    cgroup_namespace: str
    mount_namespace: str
    user_namespace: str
    host_pid_namespace: str
    host_cgroup_namespace: str
    host_mount_namespace: str
    host_user_namespace: str
    cgroup: str
    guest_boot_id: str
    root_device: int
    root_inode: int
    root_uid: int
    root_gid: int


def _facts(proc_fd: int, root_fd: int, controller: Controller, guest_group: str) -> GuestLeaderFacts:
    controller.require_alive()
    raw_stat = _read(proc_fd, "stat")
    marker = raw_stat.rfind(PROC_STAT_END)
    fields = raw_stat[marker + 1 :].split()
    if (
        marker < 0
        or len(fields) <= PROC_START_INDEX
        or fields[0] in set(TerminalProcessState)
        or int(fields[PROC_START_INDEX]) != controller.start_ticks
    ):
        raise ValueError(ERROR_BINDING)
    status: dict[str, list[str]] = {}
    for line in _read(proc_fd, "status").splitlines():
        name, separator, body = line.partition(":")
        if separator:
            if name in status:
                raise ValueError(ERROR_BINDING)
            status[name] = body.split()
    uid_map, gid_map = _read(proc_fd, "uid_map"), _read(proc_fd, "gid_map")
    root_uid, root_gid = _root_id(uid_map), _root_id(gid_map)
    nspid = [int(value) for value in status.get("NSpid", [])]
    if (
        len(nspid) < 2
        or nspid[0] != controller.pid
        or nspid[-1] != 1
        or any(value <= 0 for value in nspid)
        or status.get("Uid") != [str(root_uid)] * 4
        or status.get("Gid") != [str(root_gid)] * 4
        or controller.uid != root_uid
    ):
        raise ValueError(ERROR_BINDING)
    namespaces = tuple(os.readlink("ns/" + name, dir_fd=proc_fd) for name in NAMESPACES)
    host_namespaces = tuple(os.readlink("/proc/self/ns/" + name) for name in NAMESPACES)
    if any(value == outside for value, outside in zip(namespaces, host_namespaces, strict=True)):
        raise ValueError(ERROR_BINDING)
    cgroup = _read(proc_fd, "cgroup")
    rows = cgroup.splitlines()
    if len(rows) != 1 or not rows[0].startswith("0::/"):
        raise ValueError(ERROR_BINDING)
    actual_group = rows[0][3:]
    if actual_group != guest_group and not actual_group.startswith(guest_group + "/"):
        raise ValueError(ERROR_BINDING)
    root = os.fstat(root_fd)
    linked = os.stat("root", dir_fd=proc_fd)
    if (
        not stat.S_ISDIR(root.st_mode)
        or (root.st_dev, root.st_ino, root.st_uid, root.st_gid)
        != (linked.st_dev, linked.st_ino, linked.st_uid, linked.st_gid)
        or root.st_uid != root_uid
        or root.st_gid != root_gid
        or root.st_mode & 0o022
    ):
        raise ValueError(ERROR_BINDING)
    boot = _boot(root_fd)
    if boot == controller.boot_id:
        raise ValueError(ERROR_BINDING)
    controller.require_alive()
    return GuestLeaderFacts(
        controller,
        uid_map,
        gid_map,
        namespaces[0],
        namespaces[1],
        namespaces[2],
        namespaces[3],
        host_namespaces[0],
        host_namespaces[1],
        host_namespaces[2],
        host_namespaces[3],
        cgroup,
        boot,
        root.st_dev,
        root.st_ino,
        root_uid,
        root_gid,
    )


class GuestBinding:
    """Retain the original process/root descriptors; invalidation cannot be repaired by reopening."""

    def __init__(
        self, proc_fd: int, root_fd: int, registration: MachineRead, guest: UnitRead, facts: GuestLeaderFacts
    ) -> None:
        self.proc_fd = proc_fd
        self.root_fd = root_fd
        self.registration = registration
        self.guest = guest
        self.facts = facts
        self.failure: BaseException | None = None

    def record(self) -> JsonObject:
        """Render captured facts and the native registration, without representing FDs as durable capabilities."""
        return {
            "leader": parse_object(json.dumps(asdict(self.facts), allow_nan=False).encode(UTF8)),
            "registration": {
                "owner": self.registration.owner,
                "object_path": self.registration.object_path,
                "properties": dict(self.registration.properties),
                "begin_sequence": self.registration.begin_sequence,
                "sequence": self.registration.sequence,
                "observed_ns": self.registration.observed_ns,
            },
        }

    @classmethod
    def capture(
        cls, registration: MachineRead, guest: UnitRead, rootfs: Path, host_boot_id: str, deadline: AdmittedDeadline
    ) -> GuestBinding:
        """Bind one native registration to the caller's original active guest invocation, without adopting a successor."""
        _before_cutoff(deadline)
        properties = registration.properties
        leader = properties.get("Leader")
        if (
            os.geteuid() != 0
            or type(leader) is not int
            or not 1 < leader < UINT_MAX
            or properties.get("Name") != rootfs.name
            or properties.get("Unit") != guest.name
            or properties.get("RootDirectory") != str(rootfs)
            or properties.get("Service") != "systemd-nspawn"
            or properties.get("Class") != "container"
            or guest.unit.get(Property.ACTIVE_STATE) != ACTIVE
        ):
            raise ValueError(ERROR_BINDING)
        controller = Controller.capture(leader)
        if controller.boot_id != host_boot_id:
            raise ValueError(ERROR_BINDING)
        group = text(guest.specific, Property.CONTROL_GROUP)
        if group == "/" or not group.startswith("/"):
            raise ValueError(ERROR_BINDING)
        proc_fd = os.open("/proc/" + str(leader), DIRECTORY_FLAGS)
        root_fd = -1
        try:
            # This specific procfs magic link supplies the guest's actual mounts; never replace it with rootfs.
            root_fd = os.open("root", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=proc_fd)
            facts = _facts(proc_fd, root_fd, controller, group)
            binding = cls(proc_fd, root_fd, registration, guest, facts)
            binding.require_original(deadline)
            return binding
        except BaseException:
            close_evidence_descriptors(root_fd, proc_fd)
            raise

    def require_original(self, deadline: AdmittedDeadline) -> GuestLeaderFacts:
        """Check at an actual caller frontier, using only the original handles and sticky failure."""
        if self.failure is not None:
            raise RuntimeError(ERROR_BINDING) from self.failure
        try:
            _before_cutoff(deadline)
            current = _facts(
                self.proc_fd, self.root_fd, self.facts.controller, text(self.guest.specific, Property.CONTROL_GROUP)
            )
            # Placement must remain within the original guest service; movement inside it
            # is not a new leader, namespace or root and is retained as a current fact.
            if replace(current, cgroup=self.facts.cgroup) != self.facts:
                raise ValueError(ERROR_BINDING)
            _before_cutoff(deadline)
            return current
        except BaseException as error:
            self.failure = error
            raise

    def close(self) -> None:
        """Close only retained guest evidence handles; this neither stops nor deletes the guest."""
        if self.failure is None:
            self.failure = RuntimeError(ERROR_BINDING)
        descriptors = self.root_fd, self.proc_fd
        self.root_fd = self.proc_fd = -1
        close_evidence_descriptors(*descriptors)

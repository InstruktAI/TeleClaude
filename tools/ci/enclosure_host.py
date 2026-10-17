"""One-shot host compatibility and fixed substrate reads before privileged provisioning."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.acceptance_interpreter_metadata import _file_identity
from tools.ci.enclosure_contract import (
    AdmittedDeadline,
    Field,
    JsonObject,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_journal import Controller
from tools.ci.enclosure_native import INVENTORY_ARGUMENTS, NativeQuery, query_native
from tools.ci.enclosure_preflight import InitialMachines, inspect_initial_machines, require_initial_machines

ROOT: Final = Path("/")
PROC_PYTHON: Final = Path("/proc/self/exe")
ARCHITECTURE_ARGUMENTS: Final = ("/usr/bin/dpkg", "--print-architecture")
CONTAINER_PACKAGE: Final = "systemd-container"
INSTALLED: Final = "install ok installed"
NOT_INSTALLED: Final = "unknown ok not-installed"
TAB: Final = "\t"
UTF8: Final = "utf-8"
IMAGE_SHA256: Final = "sha256"
IMAGE_SIZE_BYTES: Final = "size_bytes"
IMAGE_DEVICE: Final = "device"
IMAGE_INODE: Final = "inode"
ERROR_HOST: Final = "the actual host image, kernel, interpreter or fixed package closure differs from the reviewed lock"
ERROR_FILE: Final = "a declared host substrate file differs from its lock: {path}"
ERROR_DEADLINE: Final = "host preflight exhausted its original admitted allowance"


class Key(StrEnum):
    """Fields of the already approved host package and activation declarations."""

    HOST = "host"
    HOST_COMPATIBILITY = "host_compatibility"
    HOST_CLOSURE = "host_closure"
    FINAL_PACKAGES = "final_packages"
    IMAGE = "image"
    ACCEPTED_IMAGE = "accepted_image"
    KERNEL = "kernel"
    ARCHITECTURE = "architecture"
    NAME = "name"
    VERSION = "version"
    PACKAGE = "package"
    PYTHON_BINARY = "python_binary"
    ACTIVATION_SOURCES = "activation_sources"
    SCOPE = "scope"
    KIND = "kind"
    TARGET = "target"


class Kind(StrEnum):
    """The native object kinds in the fixed activation census."""

    FILE = "file"
    SYMLINK = "symlink"


@dataclass(frozen=True)
class HostSubstrateFacts:
    """Capture-point substrate facts; these supply neither effective graph nor P4 continuity."""

    image: str
    kernel: str
    architecture: str
    host_boot_id: str
    pid1_start_ticks: int
    uid: int
    inventory_sha256: str
    container_installed: bool
    matched_packages: int
    activation_files: int
    python_sha256: str
    observed_ns: int
    initial_machines: InitialMachines


def _require_time(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_DEADLINE)


def _package_presence(lock: JsonObject, raw: bytes) -> tuple[bool, int]:
    rows = object_value(lock[Key.HOST_CLOSURE])[Key.FINAL_PACKAGES]
    if not isinstance(rows, list):
        raise ValueError(ERROR_HOST)
    expected: dict[str, tuple[str, str]] = {}
    for value in rows:
        row = object_value(value)
        name = text(row, Key.NAME)
        if name in expected:
            raise ValueError(ERROR_HOST)
        expected[name] = (text(row, Key.VERSION), text(row, Key.ARCHITECTURE))
    if CONTAINER_PACKAGE not in expected:
        raise ValueError(ERROR_HOST)
    installed: set[str] = set()
    seen: set[str] = set()
    for line in raw.decode(UTF8).splitlines():
        fields = line.split(TAB)
        if len(fields) != 4:
            raise ValueError(ERROR_HOST)
        name, version, architecture, status = fields
        if name not in expected:
            continue
        if name in seen:
            raise ValueError(ERROR_HOST)
        seen.add(name)
        if name == CONTAINER_PACKAGE and status == NOT_INSTALLED:
            continue
        if status != INSTALLED or (version, architecture) != expected[name]:
            raise ValueError(ERROR_HOST)
        installed.add(name)
    if set(expected) - installed - {CONTAINER_PACKAGE}:
        raise ValueError(ERROR_HOST)
    return CONTAINER_PACKAGE in installed, len(installed)


def _locked_file(row: JsonObject, deadline: AdmittedDeadline) -> None:
    _require_time(deadline)
    relative = Path(text(row, Field.PATH))
    if relative.is_absolute() or any(part == os.pardir for part in relative.parts):
        raise ValueError(ERROR_HOST)
    path = ROOT / relative
    before = path.lstat()
    if before.st_uid != 0 or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        # Symlink permissions are nominal; ownership and the exact link text bind these rows.
        if not stat.S_ISLNK(before.st_mode) or before.st_uid != 0:
            raise ValueError(ERROR_FILE.format(path=relative))
    kind = Kind(text(row, Key.KIND))
    if kind == Kind.SYMLINK:
        if not stat.S_ISLNK(before.st_mode) or os.readlink(path) != text(row, Key.TARGET):
            raise ValueError(ERROR_FILE.format(path=relative))
    else:
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(ERROR_FILE.format(path=relative))
        identity = _file_identity(path)
        if (
            identity[IMAGE_SHA256] != text(row, Field.SHA256)
            or identity[IMAGE_SIZE_BYTES] != positive_integer(row, Field.BYTES)
            or identity[IMAGE_DEVICE] != before.st_dev
            or identity[IMAGE_INODE] != before.st_ino
        ):
            raise ValueError(ERROR_FILE.format(path=relative))
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError(ERROR_FILE.format(path=relative))
    _require_time(deadline)


def inspect_host_substrate(
    package: StaticPackage,
    image_version: str,
    query: NativeQuery,
    deadline: AdmittedDeadline,
    owned_units: frozenset[str],
) -> HostSubstrateFacts:
    """Check fixed declarations without installing, enabling, starting or repairing anything."""
    _require_time(deadline)
    lock = parse_object(package.lock_bytes)
    recipe = parse_object(package.recipe_bytes)
    host = object_value(recipe[Key.HOST])
    compatibility = object_value(lock[Key.HOST_COMPATIBILITY])
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    kernel = os.uname().release
    architecture = query_native(ARCHITECTURE_ARGUMENTS, query, deadline, cap).decode(UTF8).strip()
    if (
        os.geteuid() != 0
        or image_version != text(host, Key.ACCEPTED_IMAGE)
        or image_version != text(compatibility, Key.IMAGE)
        or kernel != text(host, Key.KERNEL)
        or kernel != text(compatibility, Key.KERNEL)
        or architecture != text(host, Key.ARCHITECTURE)
    ):
        raise ValueError(ERROR_HOST)
    inventory = query_native(INVENTORY_ARGUMENTS, query, deadline, cap)
    container_installed, matched_packages = _package_presence(lock, inventory)
    initial_machines = inspect_initial_machines(owned_units, query, deadline, cap)
    require_initial_machines(initial_machines, container_installed=container_installed)
    python_rows = lock[Key.PYTHON_BINARY]
    activation_rows = lock[Key.ACTIVATION_SOURCES]
    if not isinstance(python_rows, list) or len(python_rows) != 1 or not isinstance(activation_rows, list):
        raise ValueError(ERROR_HOST)
    python = object_value(python_rows[0])
    _locked_file(python, deadline)
    actual_python = _file_identity(PROC_PYTHON)
    if actual_python[IMAGE_SHA256] != text(python, Field.SHA256) or actual_python[IMAGE_SIZE_BYTES] != positive_integer(
        python, Field.BYTES
    ):
        raise ValueError(ERROR_HOST)
    activation_count = 0
    for value in activation_rows:
        row = object_value(value)
        if row.get(Key.SCOPE) != Key.HOST:
            continue
        if text(row, Key.PACKAGE) == CONTAINER_PACKAGE and not container_installed:
            continue
        _locked_file(row, deadline)
        activation_count += 1
    pid1 = Controller.capture(1)
    _require_time(deadline)
    return HostSubstrateFacts(
        image_version,
        kernel,
        architecture,
        pid1.boot_id,
        pid1.start_ticks,
        os.geteuid(),
        hashlib.sha256(inventory).hexdigest(),
        container_installed,
        matched_packages,
        activation_count,
        text(python, Field.SHA256),
        time.monotonic_ns(),
        initial_machines,
    )

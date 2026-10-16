"""Offline guest file-data materialization through the native archive tools."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    QUALIFICATION_FILE,
    RECIPE_FILE,
    STATIC_FILE,
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

type NativeCommand = Callable[[tuple[str, ...], float], int | None]

READ_BINARY: Final = "rb"
SHA256: Final = "sha256"
EXCLUSIVE_BINARY: Final = "xb"
TAR: Final = "/usr/bin/tar"
DPKG_DEB: Final = "/usr/bin/dpkg-deb"
TAR_EXTRACT: Final = "--extract"
TAR_FILE: Final = "--file"
TAR_DIRECTORY: Final = "--directory"
TAR_NUMERIC_OWNER: Final = "--numeric-owner"
DPKG_EXTRACT: Final = "--extract"
GUEST_PREFIX: Final = "guest:/"
SUDOERS: Final = "guest.sudoers"
CONTROL_ROOT: Final = Path("var/lib/teleclaude-runtime-acceptance")
STATIC_SUBDIRECTORY: Final = "static"
SOURCE_DIRECTORY: Final = Path("srv/teleclaude-candidate")
NANOSECONDS: Final = 1_000_000_000
ERROR_DATA: Final = "a declared guest archive is missing or disagrees with its byte lock: {digest}"
ERROR_ROOT: Final = "guest file-data materialization requires its new declared rootfs and privileged owner"
ERROR_COMMAND: Final = "native file-data extraction did not complete: {executable}, exit {status}"
ERROR_DEADLINE: Final = "native file-data materialization exhausted its original admitted allowance"
ERROR_DESTINATION: Final = "a guest declaration resolves outside the owned rootfs"


class Key(StrEnum):
    """Fields consumed from the reviewed provisioning declarations."""

    HOST = "host"
    ROOTFS = "rootfs"
    GUEST_BASE = "guest_base"
    GUEST_CLOSURE = "guest_closure"
    FINAL_PACKAGES = "final_packages"
    ARCHIVE_URL = "archive_url"
    UNIT_DESTINATIONS = "unit_destinations"
    GUEST = "guest"
    PACKAGE_SERVICE_POLICY = "package_service_policy"
    PROSPECTIVE_SOURCE = "prospective_source"
    INSTALLED_PATH = "installed_path"


def _require_time(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_DEADLINE)


def _archive(row: JsonObject, inputs: Mapping[str, Path], deadline: AdmittedDeadline) -> Path:
    _require_time(deadline)
    digest = text(row, Field.SHA256)
    require_hex(digest, 64)
    if digest not in inputs:
        raise ValueError(ERROR_DATA.format(digest=digest))
    path = inputs[digest].resolve(strict=True)
    with path.open(mode=READ_BINARY) as handle:
        before = os.fstat(handle.fileno())
        found = hashlib.file_digest(handle, SHA256).hexdigest()
        after = os.fstat(handle.fileno())
    if (
        found != digest
        or after.st_size != positive_integer(row, Field.BYTES)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    ):
        raise ValueError(ERROR_DATA.format(digest=digest))
    _require_time(deadline)
    return path


def _command(argv: tuple[str, ...], run: NativeCommand, deadline: AdmittedDeadline, cap: int) -> None:
    end = deadline.command_end(cap)
    remaining = min(float(cap), (end - time.monotonic_ns()) / NANOSECONDS)
    if remaining <= 0:
        raise TimeoutError(ERROR_DEADLINE)
    status = run(argv, remaining)
    if time.monotonic_ns() >= end:
        raise TimeoutError(ERROR_DEADLINE)
    if status != 0:
        raise RuntimeError(ERROR_COMMAND.format(executable=argv[0], status=status))


def materialize_os_data(
    package: StaticPackage,
    run_token: str,
    inputs: Mapping[str, Path],
    run: NativeCommand,
    deadline: AdmittedDeadline,
) -> Path:
    """Extract only declared base/package data; this neither installs nor configures a package."""
    require_hex(run_token, 32)
    if os.geteuid() != 0:
        raise ValueError(ERROR_ROOT)
    recipe = parse_object(package.recipe_bytes)
    host = object_value(recipe[Key.HOST])
    rootfs = Path(text(host, Key.ROOTFS).format(run_token=run_token))
    lock = parse_object(package.lock_bytes)
    base = _archive(object_value(lock[Key.GUEST_BASE]), inputs, deadline)
    rows = object_value(lock[Key.GUEST_CLOSURE])[Key.FINAL_PACKAGES]
    if not isinstance(rows, list):
        raise ValueError(ERROR_ROOT)
    archives: list[Path] = []
    for value in rows:
        row = object_value(value)
        if Key.ARCHIVE_URL in row:
            archives.append(_archive(row, inputs, deadline))
    budget = object_value(recipe[Field.BUDGET_SECONDS])
    cap = positive_integer(budget, Field.NORMAL_COMMAND_MAX)
    deadline.command_end(cap)
    parent_fd = os.open(rootfs.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.mkdir(rootfs.name, mode=0o755, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    # Native tar and dpkg-deb own archive decoding; --extract runs no package control scripts.
    _command((TAR, TAR_EXTRACT, TAR_FILE, str(base), TAR_DIRECTORY, str(rootfs), TAR_NUMERIC_OWNER), run, deadline, cap)
    for archive in archives:
        _command((DPKG_DEB, DPKG_EXTRACT, str(archive), str(rootfs)), run, deadline, cap)
    return rootfs


def _guest_path(rootfs: Path, declared: str) -> Path:
    if not declared.startswith(GUEST_PREFIX):
        raise ValueError(ERROR_DESTINATION)
    relative = Path(declared[len(GUEST_PREFIX) :])
    root = rootfs.resolve(strict=True)
    path = root / relative
    if relative.is_absolute() or not path.parent.resolve().is_relative_to(root):
        raise ValueError(ERROR_DESTINATION)
    return path


def _write_data(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with path.open(mode=EXCLUSIVE_BINARY) as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def stage_guest_declarations(
    rootfs: Path,
    package: StaticPackage,
    run_token: str,
    commit: str,
    tree: str,
    selection: str,
    deadline: AdmittedDeadline,
) -> None:
    """Stage exact guest declarations and the source-owned service policy without enabling units."""
    _require_time(deadline)
    recipe = parse_object(package.recipe_bytes)
    expected_root = Path(text(object_value(recipe[Key.HOST]), Key.ROOTFS).format(run_token=run_token))
    if os.geteuid() != 0 or rootfs != expected_root:
        raise ValueError(ERROR_ROOT)
    rendered = package.render(run_token=run_token, candidate_sha=commit, candidate_tree=tree, selection=selection)
    destinations = object_value(recipe[Key.UNIT_DESTINATIONS])
    for name, destination in destinations.items():
        if isinstance(destination, str) and destination.startswith(GUEST_PREFIX):
            _require_time(deadline)
            _write_data(_guest_path(rootfs, destination), rendered[name], 0o440 if name == SUDOERS else 0o644)
    guest = object_value(recipe[Key.GUEST])
    policy = object_value(guest[Key.PACKAGE_SERVICE_POLICY])
    source = (rootfs / SOURCE_DIRECTORY / text(policy, Key.PROSPECTIVE_SOURCE)).resolve(strict=True)
    if not source.is_relative_to((rootfs / SOURCE_DIRECTORY).resolve(strict=True)):
        raise ValueError(ERROR_DESTINATION)
    _require_time(deadline)
    _write_data(_guest_path(rootfs, text(policy, Key.INSTALLED_PATH)), source.read_bytes(), 0o755)
    static = rootfs / CONTROL_ROOT / STATIC_SUBDIRECTORY
    for name, data in (
        (STATIC_FILE, package.lock_bytes),
        (RECIPE_FILE, package.recipe_bytes),
        (QUALIFICATION_FILE, package.qualification_bytes),
    ):
        _require_time(deadline)
        _write_data(static / name, data, 0o644)
    _require_time(deadline)

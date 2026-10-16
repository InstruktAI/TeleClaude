"""Offline guest file-data materialization through the native archive tools."""

from __future__ import annotations

import hashlib
import os
import shutil
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
UTF8: Final = "utf-8"
SHA256: Final = "sha256"
EXCLUSIVE_BINARY: Final = "xb"
TAR: Final = "/usr/bin/tar"
DPKG_DEB: Final = "/usr/bin/dpkg-deb"
TAR_EXTRACT: Final = "--extract"
TAR_FILE: Final = "--file"
TAR_DIRECTORY: Final = "--directory"
TAR_NUMERIC_OWNER: Final = "--numeric-owner"
TAR_STRIP_ONE: Final = "--strip-components=1"
TAR_NO_SAME_OWNER: Final = "--no-same-owner"
DPKG_EXTRACT: Final = "--extract"
GIT: Final = "/usr/bin/git"
GIT_OPTIONS: Final = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.autocrlf=false")
GIT_CLONE: Final = ("clone", "--no-checkout", "--no-local", "--no-tags", "--template=", "--")
GIT_DIRECTORY: Final = "-C"
GIT_CHECKOUT: Final = ("checkout", "--detach")
GIT_CHECK_INDEX: Final = ("diff-index", "--quiet", "--cached", "--no-ext-diff")
GIT_CHECK_FILES: Final = ("diff", "--quiet", "--no-ext-diff", "--no-textconv")
END_OPTIONS: Final = "--"
GIT_HEAD: Final = Path(".git/HEAD")
PROVISION_ENVIRONMENT: Final = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
GUEST_PREFIX: Final = "guest:/"
SUDOERS: Final = "guest.sudoers"
CONTROL_ROOT: Final = Path("var/lib/teleclaude-runtime-acceptance")
STATIC_SUBDIRECTORY: Final = "static"
SOURCE_DIRECTORY: Final = Path("srv/teleclaude-candidate")
GUEST_ARCHIVE_DIRECTORY: Final = Path("/var/lib/teleclaude-runtime-acceptance/archives")
GUEST_TOOL_DIRECTORY: Final = Path("/var/lib/teleclaude-runtime-acceptance/tools")
TOOL_PREFIX: Final = Path("usr/local")
BIN_DIRECTORY: Final = "bin"
NODE_BINARY: Final = "node"
UV_BINARY: Final = "uv"
UV_ARCHIVE: Final = "uv.tar.gz"
NODE_ARCHIVE: Final = "node.tar.xz"
TGZ_SUFFIX: Final = ".tgz"
DEB_SUFFIX: Final = ".deb"
NANOSECONDS: Final = 1_000_000_000
ERROR_DATA: Final = "a declared guest archive is missing or disagrees with its byte lock: {digest}"
ERROR_ROOT: Final = "guest file-data materialization requires its new declared rootfs and privileged owner"
ERROR_COMMAND: Final = "native file-data extraction did not complete: {executable}, exit {status}"
ERROR_DEADLINE: Final = "native file-data materialization exhausted its original admitted allowance"
ERROR_DESTINATION: Final = "a guest declaration resolves outside the owned rootfs"
ERROR_SOURCE: Final = "the new guest candidate does not match its admitted commit, tree and source basis"


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
    NODE = "node"
    TOOL_ARCHIVES = "tool_archives"
    TOOL_BINARIES = "tool_binaries"
    NPM_TOOLS = "npm_tools"
    FILE = "file"
    ARCHIVE = "archive"
    MEMBER = "member"


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


def stage_guest_archives(
    rootfs: Path, package: StaticPackage, run_token: str, inputs: Mapping[str, Path], deadline: AdmittedDeadline
) -> None:
    """Copy only the declared package archives for later namespace-confined unpack/configuration."""
    require_hex(run_token, 32)
    recipe = parse_object(package.recipe_bytes)
    expected_root = Path(text(object_value(recipe[Key.HOST]), Key.ROOTFS).format(run_token=run_token))
    if os.geteuid() != 0 or rootfs != expected_root:
        raise ValueError(ERROR_ROOT)
    rows = object_value(parse_object(package.lock_bytes)[Key.GUEST_CLOSURE])[Key.FINAL_PACKAGES]
    if not isinstance(rows, list):
        raise ValueError(ERROR_ROOT)
    for value in rows:
        row = object_value(value)
        if Key.ARCHIVE_URL not in row:
            continue
        source = _archive(row, inputs, deadline)
        guest_path = GUEST_ARCHIVE_DIRECTORY / (text(row, Field.SHA256) + DEB_SUFFIX)
        target = _guest_path(rootfs, GUEST_PREFIX + str(guest_path.relative_to(guest_path.anchor)))
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open(mode=READ_BINARY) as original, target.open(mode=EXCLUSIVE_BINARY) as copied:
            os.fchmod(copied.fileno(), 0o644)
            shutil.copyfileobj(original, copied)
            copied.flush()
            os.fsync(copied.fileno())
        _require_time(deadline)


def stage_candidate(
    rootfs: Path,
    package: StaticPackage,
    run_token: str,
    source_root: Path,
    commit: str,
    tree: str,
    run: NativeCommand,
    deadline: AdmittedDeadline,
) -> Path:
    """Materialize the checked candidate through native Git with no provisioning-time hooks."""
    require_hex(run_token, 32)
    require_hex(commit, 40)
    require_hex(tree, 40)
    recipe = parse_object(package.recipe_bytes)
    expected_root = Path(text(object_value(recipe[Key.HOST]), Key.ROOTFS).format(run_token=run_token))
    if os.geteuid() != 0 or rootfs != expected_root:
        raise ValueError(ERROR_ROOT)
    _require_time(deadline)
    source_root = source_root.resolve(strict=True)
    package.validate_source(source_root)
    target = _guest_path(rootfs, GUEST_PREFIX + str(SOURCE_DIRECTORY))
    if target.exists() or target.is_symlink():
        raise ValueError(ERROR_SOURCE)
    target.parent.mkdir(parents=True, exist_ok=True)
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    # The native adapter supplies PROVISION_ENVIRONMENT, with no ambient user/system Git config.
    _command((GIT, *GIT_OPTIONS, *GIT_CLONE, str(source_root), str(target)), run, deadline, cap)
    prefix = (GIT, *GIT_OPTIONS, GIT_DIRECTORY, str(target))
    _command((*prefix, *GIT_CHECKOUT, commit, END_OPTIONS), run, deadline, cap)
    if (target / GIT_HEAD).read_text(encoding=UTF8).strip() != commit:
        raise ValueError(ERROR_SOURCE)
    _command((*prefix, *GIT_CHECK_INDEX, tree, END_OPTIONS), run, deadline, cap)
    _command((*prefix, *GIT_CHECK_FILES, tree, END_OPTIONS), run, deadline, cap)
    package.validate_source(target)
    _require_time(deadline)
    return target


def stage_bootstrap_tools(
    rootfs: Path,
    package: StaticPackage,
    run_token: str,
    inputs: Mapping[str, Path],
    run: NativeCommand,
    deadline: AdmittedDeadline,
) -> None:
    """Stage fixed Node/uv bytes and npm archives, executing no tool outside the guest."""
    require_hex(run_token, 32)
    recipe = parse_object(package.recipe_bytes)
    expected_root = Path(text(object_value(recipe[Key.HOST]), Key.ROOTFS).format(run_token=run_token))
    if os.geteuid() != 0 or rootfs != expected_root:
        raise ValueError(ERROR_ROOT)
    lock = parse_object(package.lock_bytes)
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    node = _archive(object_value(lock[Key.NODE]), inputs, deadline)
    archives, npm = lock[Key.TOOL_ARCHIVES], lock[Key.NPM_TOOLS]
    if not isinstance(archives, list) or not isinstance(npm, list):
        raise ValueError(ERROR_DATA.format(digest=UV_ARCHIVE))
    uv_rows = [object_value(row) for row in archives if object_value(row).get(Key.FILE) == UV_ARCHIVE]
    if len(uv_rows) != 1:
        raise ValueError(ERROR_DATA.format(digest=UV_ARCHIVE))
    uv = _archive(uv_rows[0], inputs, deadline)
    prefix = _guest_path(rootfs, GUEST_PREFIX + str(TOOL_PREFIX))
    prefix.mkdir(parents=True, exist_ok=True)
    bin_directory = prefix / BIN_DIRECTORY
    if any(path.exists() or path.is_symlink() for path in (bin_directory / NODE_BINARY, bin_directory / UV_BINARY)):
        raise ValueError(ERROR_ROOT)
    _command(
        (TAR, TAR_EXTRACT, TAR_FILE, str(node), TAR_DIRECTORY, str(prefix), TAR_STRIP_ONE, TAR_NO_SAME_OWNER),
        run,
        deadline,
        cap,
    )
    bin_directory.mkdir(exist_ok=True)
    _command(
        (TAR, TAR_EXTRACT, TAR_FILE, str(uv), TAR_DIRECTORY, str(bin_directory), TAR_STRIP_ONE, TAR_NO_SAME_OWNER),
        run,
        deadline,
        cap,
    )
    verify_bootstrap_binaries(package, prefix, deadline)
    for value in npm:
        row = object_value(value)
        source = _archive(row, inputs, deadline)
        guest_path = GUEST_TOOL_DIRECTORY / (text(row, Field.SHA256) + TGZ_SUFFIX)
        target = _guest_path(rootfs, GUEST_PREFIX + str(guest_path.relative_to(guest_path.anchor)))
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open(mode=READ_BINARY) as original, target.open(mode=EXCLUSIVE_BINARY) as copied:
            os.fchmod(copied.fileno(), 0o644)
            shutil.copyfileobj(original, copied)
            copied.flush()
            os.fsync(copied.fileno())
        _require_time(deadline)


def verify_bootstrap_binaries(package: StaticPackage, prefix: Path, deadline: AdmittedDeadline) -> None:
    """Bind the explicitly locked native images at staging and after guest OS package configuration."""
    binaries = parse_object(package.lock_bytes)[Key.TOOL_BINARIES]
    if not isinstance(binaries, list):
        raise ValueError(ERROR_ROOT)
    for value in binaries:
        row = object_value(value)
        archive_name = text(row, Key.ARCHIVE)
        member = Path(text(row, Key.MEMBER))
        if member.is_absolute() or len(member.parts) < 2:
            raise ValueError(ERROR_ROOT)
        base = (
            prefix if archive_name == NODE_ARCHIVE else prefix / BIN_DIRECTORY if archive_name == UV_ARCHIVE else None
        )
        if base is None:
            raise ValueError(ERROR_ROOT)
        binary = base.joinpath(*member.parts[1:]).resolve(strict=True)
        if not binary.is_relative_to(base.resolve(strict=True)) or binary.stat().st_uid != 0:
            raise ValueError(ERROR_ROOT)
        _archive(row, {text(row, Field.SHA256): binary}, deadline)


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
    control = _guest_path(rootfs, GUEST_PREFIX + str(CONTROL_ROOT))
    control.mkdir(parents=True, exist_ok=True)
    control_fd = os.open(control, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(control_fd).st_uid != 0:
            raise ValueError(ERROR_ROOT)
        # Root-owned sticky entries protect the manifest/journals while runner owns its report/temp entries.
        os.fchmod(control_fd, 0o1777)
        os.fsync(control_fd)
    finally:
        os.close(control_fd)
    static = control / STATIC_SUBDIRECTORY
    for name, data in (
        (STATIC_FILE, package.lock_bytes),
        (RECIPE_FILE, package.recipe_bytes),
        (QUALIFICATION_FILE, package.qualification_bytes),
    ):
        _require_time(deadline)
        _write_data(static / name, data, 0o644)
    _require_time(deadline)

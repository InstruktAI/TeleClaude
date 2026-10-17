"""Finite native dpkg configuration/trigger inputs, without package invocation or admission."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
import time
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import AdmittedDeadline, JsonObject, JsonValue
from tools.ci.enclosure_native import read_native_stdout

CONFIGURATION: Final = Path("/etc/dpkg")
TRIGGER_INPUTS: Final = (
    Path("/var/lib/dpkg/triggers/File"),
    Path("/var/lib/dpkg/triggers/Unincorp"),
    Path("/var/lib/dpkg/info/dbus.postinst"),
    Path("/var/lib/dpkg/info/dbus.triggers"),
)
CONFIG_NAME: Final = re.compile(r"[A-Za-z0-9_-]+")
DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
ERROR_INPUT: Final = "native dpkg input was unreadable, incomplete, changed, unprotected or late"


class DpkgInputError(RuntimeError):
    """Keep original partial observations when the finite read cannot complete."""

    def __init__(self, snapshot: JsonObject) -> None:
        super().__init__(ERROR_INPUT)
        self.snapshot = snapshot


def _before_cutoff(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_INPUT)


def _identity(native: os.stat_result) -> JsonObject:
    return {
        "device": native.st_dev,
        "inode": native.st_ino,
        "mode": native.st_mode,
        "uid": native.st_uid,
        "gid": native.st_gid,
        "bytes": native.st_size,
        "mtime_ns": native.st_mtime_ns,
        "ctime_ns": native.st_ctime_ns,
    }


def _protected_path(path: Path, deadline: AdmittedDeadline) -> Path:
    _before_cutoff(deadline)
    physical = path.resolve(strict=False)
    # Native fopen/scandir follows root-owned links; preserve that supported shape.
    for ancestor in (path, *path.parents, physical, *physical.parents):
        _before_cutoff(deadline)
        try:
            native = ancestor.lstat()
        except FileNotFoundError:
            continue
        if native.st_uid != 0 or (not stat.S_ISLNK(native.st_mode) and native.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ValueError(ERROR_INPUT)
    return physical


def _file(path: Path, deadline: AdmittedDeadline, files: list[JsonValue]) -> None:
    row: JsonObject = {"path": str(path), "present": None, "started_ns": time.monotonic_ns(), "finished_ns": None}
    files.append(row)
    descriptor = -1
    try:
        physical = _protected_path(path, deadline)
        try:
            descriptor = os.open(physical, READ_FLAGS)
        except FileNotFoundError:
            # These are raw inputs: required-source presence is the consumer's distinct predicate.
            row["present"] = False
            _before_cutoff(deadline)
            return
        row["present"] = True
        row["physical_path"] = str(physical)
        before = os.fstat(descriptor)
        row["before"] = _identity(before)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError(ERROR_INPUT)
        _before_cutoff(deadline)
        data, complete = read_native_stdout(descriptor)
        row.update(
            {
                "data_base64": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "complete": complete,
            }
        )
        after = _identity(os.fstat(descriptor))
        named = _identity(path.stat())
        row["after"] = after
        row["named"] = named
        if not complete or row["before"] != after or after != named:
            raise ValueError(ERROR_INPUT)
        _before_cutoff(deadline)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        row["finished_ns"] = time.monotonic_ns()


def _configuration_directory(path: Path, deadline: AdmittedDeadline, directories: list[JsonValue]) -> tuple[str, ...]:
    row: JsonObject = {"path": str(path), "present": None, "started_ns": time.monotonic_ns(), "finished_ns": None}
    directories.append(row)
    descriptor = -1
    try:
        physical = _protected_path(path, deadline)
        try:
            descriptor = os.open(physical, DIRECTORY_FLAGS)
        except FileNotFoundError:
            row["present"] = False
            _before_cutoff(deadline)
            return ()
        row["present"] = True
        row["physical_path"] = str(physical)
        native = os.fstat(descriptor)
        before = _identity(native)
        row["before"] = before
        if native.st_uid != 0 or native.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError(ERROR_INPUT)
        names: list[str] = []
        observed_names: list[JsonValue] = []
        row["native_names"] = observed_names
        with os.scandir(descriptor) as entries:
            for entry in entries:
                _before_cutoff(deadline)
                # dpkg valid_config_filename/alphasort in the existing fixed C.UTF-8 environment.
                if CONFIG_NAME.fullmatch(entry.name) is not None:
                    names.append(entry.name)
                    observed_names.append(entry.name)
        names.sort()
        row["native_names"] = list[JsonValue](names)
        after = _identity(os.fstat(descriptor))
        named = _identity(path.stat())
        row["after"] = after
        row["named"] = named
        if before != after or after != named:
            raise ValueError(ERROR_INPUT)
        _before_cutoff(deadline)
        return tuple(names)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        row["finished_ns"] = time.monotonic_ns()


def read_install_inputs(deadline: AdmittedDeadline) -> JsonObject:
    """Observe only the finite native inputs; no expected registration, pending work or policy is invented."""
    files: list[JsonValue] = []
    directories: list[JsonValue] = []
    snapshot: JsonObject = {
        "started_ns": time.monotonic_ns(),
        "finished_ns": None,
        "files": files,
        "configuration_directories": directories,
        "error": None,
    }
    try:
        # The original fixed native environment supplies no HOME: no user cfg is selected.
        directory = CONFIGURATION / "dpkg.cfg.d"
        names = _configuration_directory(directory, deadline, directories)
        for name in names:
            _file(directory / name, deadline, files)
        _file(CONFIGURATION / "dpkg.cfg", deadline, files)
        for path in TRIGGER_INPUTS:
            _file(path, deadline, files)
        _before_cutoff(deadline)
        return snapshot
    except (OSError, ValueError, RuntimeError) as error:
        snapshot["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError(snapshot) from error
    finally:
        snapshot["finished_ns"] = time.monotonic_ns()

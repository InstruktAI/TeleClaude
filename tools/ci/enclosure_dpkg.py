"""Finite native dpkg configuration/trigger inputs, without package invocation or admission."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import stat
import time
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import AdmittedDeadline, JsonObject, JsonValue, object_value, text
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
CONFIG_READ_SIZE: Final = 1023  # Native fgets(MAX_CONFIG_LINE=1024) reserves one byte for its NUL.
OPTION_NAME: Final = re.compile(rb"[A-Za-z0-9-]*")
NATIVE_SPACE: Final = b" \t\n\r\v\f"
FIXED_ARGUMENTS: Final = (
    "/usr/bin/dpkg",
    "--root=/",
    "--instdir=/",
    "--admindir=/var/lib/dpkg",
    "--no-triggers",
    "--no-debsig",
    "--no-pager",
    # Restore the two native built-in force defaults after configuration, not arbitrary configured relaxations.
    "--refuse-all",
    "--force-security-mac,downgrade",
    "--path-include=*",
    "--debug=0",
    "--abort-after=50",
    "--log=/var/log/dpkg.log",
)
INSTALL_PREFIX: Final = (*FIXED_ARGUMENTS, "--install", "--")
DBUS_TRIGGER_ARGUMENTS: Final = (*FIXED_ARGUMENTS, "--triggers-only", "--", "dbus")
VALUE_OPTIONS: Final = frozenset(
    {
        "pre-invoke",
        "post-invoke",
        "path-exclude",
        "path-include",
        "verify-format",
        "status-logger",
        "status-fd",
        "log",
        "root",
        "abort-after",
        "admindir",
        "instdir",
        "ignore-depends",
        "debug",
    }
)
FLAG_OPTIONS: Final = frozenset(
    {
        "pending",
        "recursive",
        "no-act",
        "dry-run",
        "simulate",
        "no-pager",
        "no-debsig",
        "selected-only",
        "triggers",
        "no-triggers",
        "no-also-select",
        "skip-same-version",
        "auto-deconfigure",
        "robot",
    }
)
FORCE_OPTIONS: Final = ("no-force", "refuse", "force")
SCALAR_OVERRIDES: Final = frozenset({"root", "instdir", "admindir", "log", "abort-after", "debug"})
OUTPUT_DESCRIPTOR: Final = re.compile(rb"\+?(?:0*[12]|0[xX]0*[12])")


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


def _input_files(snapshot: JsonObject) -> dict[str, JsonObject]:
    if snapshot["error"] is not None or not isinstance(snapshot["files"], list):
        raise ValueError(ERROR_INPUT)
    files: dict[str, JsonObject] = {}
    for value in snapshot["files"]:
        row = object_value(value)
        path = text(row, "path")
        if path in files:
            raise ValueError(ERROR_INPUT)
        files[path] = row
    return files


def _input_bytes(row: JsonObject) -> bytes | None:
    if row["present"] is False:
        return None
    if row["present"] is not True or row["complete"] is not True:
        raise ValueError(ERROR_INPUT)
    encoded = row["data_base64"]
    if not isinstance(encoded, str):
        raise ValueError(ERROR_INPUT)
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != text(row, "sha256"):
        raise ValueError(ERROR_INPUT)
    return data


def _configuration_lines(data: bytes, deadline: AdmittedDeadline, options: list[JsonValue]) -> None:
    # This is the native config string grammar, not shell tokenization or an executable hook.
    with io.BytesIO(data) as stream:
        number = 0
        while chunk := stream.readline(CONFIG_READ_SIZE):
            _before_cutoff(deadline)
            number += 1
            line = chunk.split(b"\x00", 1)[0].rstrip(NATIVE_SPACE)
            if not line or line.startswith(b"#"):
                continue
            match = OPTION_NAME.match(line)
            if match is None:
                raise ValueError(ERROR_INPUT)
            end = match.end()
            value: bytes | None = None
            if end != len(line):
                # options.c overwrites one separator, then skips one further '=' if present.
                value = line[end + 1 :]
                if value.startswith(b"="):
                    value = value[1:]
                value = value.lstrip(NATIVE_SPACE)
                if value[:1] in (b"'", b'"'):
                    if value[-1:] != value[:1]:
                        raise ValueError(ERROR_INPUT)
                    value = value[1:-1]
            options.append(
                {
                    "native_line": number,
                    "option": line[:end].decode("ascii"),
                    # Native values need not be Unicode; exact bytes survive for the actual option consumer.
                    "value_base64": base64.b64encode(value).decode("ascii") if value is not None else None,
                }
            )


def parse_install_configuration(snapshot: JsonObject, deadline: AdmittedDeadline) -> JsonObject:
    """Parse captured native syntax only; known option arity/effects and fixed transaction admission remain owed."""
    result: JsonObject = {"configuration_files": [], "native_option_effects": "unproven", "error": None}
    try:
        _before_cutoff(deadline)
        files = _input_files(snapshot)
        directories = snapshot["configuration_directories"]
        if not isinstance(directories, list) or len(directories) != 1:
            raise ValueError(ERROR_INPUT)
        directory = object_value(directories[0])
        path = CONFIGURATION / "dpkg.cfg.d"
        if directory["path"] != str(path):
            raise ValueError(ERROR_INPUT)
        names: list[str] = []
        if directory["present"] is True:
            values = directory["native_names"]
            if not isinstance(values, list):
                raise ValueError(ERROR_INPUT)
            for value in values:
                if not isinstance(value, str) or CONFIG_NAME.fullmatch(value) is None:
                    raise ValueError(ERROR_INPUT)
                names.append(value)
            if names != sorted(set(names)):
                raise ValueError(ERROR_INPUT)
        elif directory["present"] is not False:
            raise ValueError(ERROR_INPUT)
        paths = [*(str(path / name) for name in names), str(CONFIGURATION / "dpkg.cfg")]
        if list(files) != [*paths, *(str(path) for path in TRIGGER_INPUTS)]:
            raise ValueError(ERROR_INPUT)
        parsed: list[JsonValue] = []
        result["configuration_files"] = parsed
        for path_name in paths:
            _before_cutoff(deadline)
            row = files[path_name]
            data = _input_bytes(row)
            options: list[JsonValue] = []
            parsed.append(
                {
                    "path": path_name,
                    "present": data is not None,
                    "sha256": row["sha256"] if data is not None else None,
                    "options": options,
                }
            )
            if data is not None:
                _configuration_lines(data, deadline, options)
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"inputs": snapshot, "configuration": result}) from error


def _option_effect(option: str, value: bytes | None) -> tuple[str, bool]:
    # options.c permits continued --force-value names only when no separate value was parsed.
    for name in FORCE_OPTIONS:
        if value is None and option.startswith(name + "-"):
            value = option[len(name) + 1 :].encode("ascii")
            option = name
            break
    takes_value = option in VALUE_OPTIONS or option in FORCE_OPTIONS
    if option not in VALUE_OPTIONS and option not in FLAG_OPTIONS and option not in FORCE_OPTIONS:
        return "unsupported_native_option_or_conflicting_action", False
    if takes_value != (value is not None):
        return "invalid_native_option_arity", False
    if option in FORCE_OPTIONS:
        # Invalid force values fail during native config parsing; 'help' instead exits0 before the action.
        return ("native_early_exit", False) if value == b"help" else ("restored_native_force_defaults", True)
    if option == "debug" and value is not None and value.startswith(b"h"):
        return "native_early_exit", False
    if option in SCALAR_OVERRIDES or option in ("triggers", "no-triggers"):
        return "fixed_command_override", True
    if option in ("path-exclude", "path-include"):
        # Native fnmatch(flags=0) '*' and last-match-wins restore all members of the authenticated archive.
        return "fixed_final_include_all", True
    if option in ("pre-invoke", "post-invoke", "status-logger"):
        # Only the shell's empty input is a known no-op; no arbitrary hook text is interpreted or executed here.
        return ("empty_native_hook", True) if value == b"" else ("unreviewed_executable_hook", False)
    if option == "ignore-depends":
        return ("empty_ignore_list", True) if value == b"" else ("additional_dependency_bypass", False)
    if option == "status-fd":
        if value is not None and OUTPUT_DESCRIPTOR.fullmatch(value.lstrip(NATIVE_SPACE)) is not None:
            return "existing_owned_stdout_or_stderr", True
        return "unreviewed_status_descriptor", False
    if option == "auto-deconfigure":
        return "additional_package_deconfiguration", False
    if option in ("no-act", "dry-run", "simulate", "selected-only", "no-also-select"):
        return "native_may_skip_or_simulate_actual_post_state_required", True
    if option == "pending":
        # packages.c rejects --pending with our explicit dbus operand before enqueue_pending.
        return "explicit_operand_prevents_generic_pending_work", True
    if option == "recursive":
        return "single_authenticated_regular_archive_operand", True
    # verify-format does not affect these package actions; the remaining recognized flags do not widen their scope.
    return "unchanged_fixed_transaction_scope", True


def bound_configuration_effects(configuration: JsonObject, deadline: AdmittedDeadline) -> JsonObject:
    """Bound options for these exact native vectors only; required source/recipient/caller admission is separate."""
    effects: list[JsonValue] = []
    result: JsonObject = {
        "scope": "fixed_container_install_and_named_dbus_trigger",
        "state": "unproven",
        "effects": effects,
        "install_prefix": list[JsonValue](INSTALL_PREFIX),
        "dbus_trigger_arguments": list[JsonValue](DBUS_TRIGGER_ARGUMENTS),
        "native_value_validation": "native_result_and_actual_post_state_required",
        "recipient_and_source_admission": "unproven",
        "error": None,
    }
    try:
        _before_cutoff(deadline)
        files = configuration["configuration_files"]
        if configuration["error"] is not None or not isinstance(files, list):
            raise ValueError(ERROR_INPUT)
        bounded = True
        for file_value in files:
            file = object_value(file_value)
            path = text(file, "path")
            options = file["options"]
            if not isinstance(options, list):
                raise ValueError(ERROR_INPUT)
            for option_value in options:
                _before_cutoff(deadline)
                row = object_value(option_value)
                option = row["option"]
                encoded = row["value_base64"]
                if not isinstance(option, str) or (encoded is not None and not isinstance(encoded, str)):
                    raise ValueError(ERROR_INPUT)
                value = base64.b64decode(encoded, validate=True) if encoded is not None else None
                effect, allowed = _option_effect(option, value)
                effects.append({"path": path, **row, "effect": effect, "bounded": allowed})
                bounded = bounded and allowed
        _before_cutoff(deadline)
        result["state"] = "bounded_for_fixed_commands" if bounded else "blocked"
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"configuration": configuration, "effects": result}) from error

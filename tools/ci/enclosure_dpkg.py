"""Finite native dpkg configuration/trigger inputs, without package invocation or admission."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import stat
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_data import DPKG_DEB, _archive
from tools.ci.enclosure_host import CONTAINER_PACKAGE, HostSubstrateFacts
from tools.ci.enclosure_native import NativeQuery, query_native, read_native_stdout

CONFIGURATION: Final = Path("/etc/dpkg")
TRIGGER_INPUTS: Final = (
    Path("/var/lib/dpkg/triggers/File"),
    Path("/var/lib/dpkg/triggers/Unincorp"),
    Path("/var/lib/dpkg/info/dbus.postinst"),
    Path("/var/lib/dpkg/info/dbus.triggers"),
    Path("/var/lib/dpkg/diversions"),
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
PACKAGE_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._-]*")
ARCHITECTURE_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
PACKAGE_STATES: Final = frozenset(
    {
        "not-installed",
        "config-files",
        "half-installed",
        "unpacked",
        "half-configured",
        "triggers-awaited",
        "triggers-pending",
        "installed",
    }
)
ACTIVATION_STATES: Final = frozenset({"triggers-awaited", "triggers-pending", "installed"})
PACKAGE_WANTS: Final = frozenset({"unknown", "install", "hold", "deinstall", "purge"})
PACKAGE_ERRORS: Final = frozenset({"ok", "reinstreq"})
DEFERRED_LINE_SIZE: Final = 2048  # Native _POSIX2_LINE_MAX on the reviewed glibc substrate.
VISIBLE_TRIGGER: Final = re.compile(rb"[\x21-\x7e]+")
DEFERRED_PACKAGE: Final = re.compile(rb"[a-z0-9-][a-z0-9:+.-]*")


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


def _container_members(raw: bytes, deadline: AdmittedDeadline) -> list[JsonValue]:
    members: list[JsonValue] = []
    for line in raw.decode("utf-8").splitlines():
        _before_cutoff(deadline)
        fields = line.split(None, 5)
        if len(fields) != 6 or not fields[0] or fields[0][0] not in "-dlh":
            raise ValueError(ERROR_INPUT)
        kind = fields[0][0]
        path = fields[5]
        if kind in "lh":
            separator = " -> " if kind == "l" else " link to "
            path, found, target = path.partition(separator)
            if not found or not target:
                raise ValueError(ERROR_INPUT)
        # This parser serves the one authenticated container archive, not arbitrary tar quoting/device formats.
        if not path.startswith("./") or "\\" in path or ".." in path.split("/"):
            raise ValueError(ERROR_INPUT)
        members.append({"archive_name": path, "kind": kind})
    if not members:
        raise ValueError(ERROR_INPUT)
    return members


def container_payload_basis(
    package: StaticPackage, inputs: Mapping[str, Path], query: NativeQuery, deadline: AdmittedDeadline
) -> JsonObject:
    """Use the authenticated fixed archive and native read-only listing, without extracting or installing it."""
    result: JsonObject = {"started_ns": time.monotonic_ns(), "finished_ns": None, "error": None}
    try:
        _before_cutoff(deadline)
        lock = parse_object(package.lock_bytes)
        rows = object_value(lock["host_closure"])["final_packages"]
        if not isinstance(rows, list):
            raise ValueError(ERROR_INPUT)
        containers = [object_value(value) for value in rows if object_value(value).get("name") == CONTAINER_PACKAGE]
        if len(containers) != 1:
            raise ValueError(ERROR_INPUT)
        declaration = containers[0]
        archive = _archive(declaration, inputs, deadline)
        cap = positive_integer(
            object_value(parse_object(package.recipe_bytes)[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX
        )
        argv = (DPKG_DEB, "--contents", "--", str(archive))
        result["archive_sha256"] = text(declaration, Field.SHA256)
        result["archive_path"] = str(archive)
        result["argv"] = list[JsonValue](argv)
        raw = query_native(argv, query, deadline, cap)
        result["contents_base64"] = base64.b64encode(raw).decode("ascii")
        result["contents_sha256"] = hashlib.sha256(raw).hexdigest()
        members = _container_members(raw, deadline)
        result["members"] = members
        result["effective_path_and_trigger_admission"] = "unproven"
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError(result) from error
    finally:
        result["finished_ns"] = time.monotonic_ns()


def bind_dbus_control_sources(snapshot: JsonObject, package: StaticPackage, deadline: AdmittedDeadline) -> JsonObject:
    """Match actual captured installed control bytes, without inventing presence, registration or trigger admission."""
    result: JsonObject = {"scope": "installed_dbus_control_bytes", "files": [], "state": "unproven", "error": None}
    try:
        _before_cutoff(deadline)
        actual = _input_files(snapshot)
        rows = parse_object(package.lock_bytes)["host_maintainer_scripts"]
        if not isinstance(rows, list):
            raise ValueError(ERROR_INPUT)
        matched: list[JsonValue] = []
        result["files"] = matched
        for name in ("postinst", "triggers"):
            _before_cutoff(deadline)
            declarations = [
                object_value(value)
                for value in rows
                if object_value(value).get("package") == "dbus" and object_value(value).get("file") == name
            ]
            if len(declarations) != 1:
                raise ValueError(ERROR_INPUT)
            declared = declarations[0]
            path = f"/var/lib/dpkg/info/dbus.{name}"
            data = _input_bytes(actual[path])
            matches = (
                data is not None
                and len(data) == positive_integer(declared, Field.BYTES)
                and hashlib.sha256(data).hexdigest() == text(declared, Field.SHA256)
            )
            matched.append({"path": path, "present": data is not None, "matches_declared_source": matches})
        result["state"] = (
            "matched"
            if all(object_value(value)["matches_declared_source"] is True for value in matched)
            else "unproven"
        )
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"inputs": snapshot, "sources": result}) from error


def _checked_metadata_line(stream: io.BytesIO, buffer_size: int, deadline: AdmittedDeadline) -> bytes | None:
    _before_cutoff(deadline)
    chunk = stream.readline(buffer_size - 1)
    if not chunk:
        return None
    # Native fgets_checked, unlike config fgets, requires a terminating newline and a nonempty C string.
    if not chunk.endswith(b"\n") or b"\x00" in chunk:
        raise ValueError(ERROR_INPUT)
    return chunk[:-1]


def _metadata_lines(data: bytes | None, deadline: AdmittedDeadline) -> list[bytes]:
    lines: list[bytes] = []
    if data is None:
        return lines
    with io.BytesIO(data) as stream:
        while (line := _checked_metadata_line(stream, 1024, deadline)) is not None:
            lines.append(line)
    return lines


def _fsys_name(name: bytes) -> bytes:
    # fsys_hash_find_node/path_skip_slash_dotslash: no realpath, interior normalization or parent expansion.
    while name.startswith(b"/") or name.startswith(b"./"):
        name = name[1:]
    return b"/" + name


def _diversion_routes(
    data: bytes | None, deadline: AdmittedDeadline, captured: list[JsonValue]
) -> tuple[dict[bytes, tuple[bytes, bytes]], set[bytes]]:
    lines = _metadata_lines(data, deadline)
    if len(lines) % 3:
        raise ValueError(ERROR_INPUT)
    routes: dict[bytes, tuple[bytes, bytes]] = {}
    occupied: set[bytes] = set()
    destinations: set[bytes] = set()
    for index in range(0, len(lines), 3):
        _before_cutoff(deadline)
        source, target, owner = _fsys_name(lines[index]), _fsys_name(lines[index + 1]), lines[index + 2]
        if source in occupied or target in occupied:
            # ensure_diversions rejects a node already participating in another diversion.
            raise ValueError(ERROR_INPUT)
        occupied.update((source, target))
        destinations.add(target)
        routes[source] = (target, owner)
        captured.append(
            {
                "source_base64": base64.b64encode(source).decode("ascii"),
                "target_base64": base64.b64encode(target).decode("ascii"),
                "owner_base64": base64.b64encode(owner).decode("ascii"),
                "local": owner == b":",
            }
        )
    return routes, destinations


def _interest_fields(specification: bytes) -> JsonObject:
    package, slash, qualifier = specification.partition(b"/")
    return {
        "package_spec_base64": base64.b64encode(package).decode("ascii"),
        "qualifier_base64": base64.b64encode(qualifier).decode("ascii") if slash else None,
        # Native unknown suffixes retain AWAIT; no invented qualifier-validity gate.
        "await": qualifier != b"noawait",
    }


def interpret_trigger_routes(snapshot: JsonObject, basis: JsonObject, deadline: AdmittedDeadline) -> JsonObject:
    """Interpret actual byte routing/registration inputs; package identity/lifecycle/deferred work remain unproven."""
    diversions: list[JsonValue] = []
    routes: list[JsonValue] = []
    interests: list[JsonValue] = []
    result: JsonObject = {
        "diversions": diversions,
        "new_member_routes": routes,
        "file_interests": interests,
        "package_identity_and_lifecycle": "unproven",
        "deferred_and_pending_work": "unproven",
        "recipient_admission": "unproven",
        "error": None,
    }
    try:
        _before_cutoff(deadline)
        files = _input_files(snapshot)
        result["diversions_present"] = files["/var/lib/dpkg/diversions"]["present"]
        result["file_interests_present"] = files["/var/lib/dpkg/triggers/File"]["present"]
        mapping, destinations = _diversion_routes(_input_bytes(files["/var/lib/dpkg/diversions"]), deadline, diversions)
        members = basis["members"]
        if basis["error"] is not None or not isinstance(members, list):
            raise ValueError(ERROR_INPUT)
        effective_paths: set[bytes] = set()
        for value in members:
            _before_cutoff(deadline)
            member = object_value(value)
            # Native tar_extractor removes trailing slashes before fsys_hash_find_node.
            name = _fsys_name(text(member, "archive_name").encode("utf-8").rstrip(b"/"))
            target, owner = mapping.get(name, (name, CONTAINER_PACKAGE.encode("ascii")))
            # pkg_hash_find_set applies ASCII c_tolower before comparing the owning package set.
            effective = target if owner.lower() != CONTAINER_PACKAGE.encode("ascii") else name
            collision = name in destinations
            if not collision:
                # New archive members use trig_file_activate of this one namenodetouse result.
                effective_paths.add(effective)
            routes.append(
                {
                    "archive_name": member["archive_name"],
                    "native_name_base64": base64.b64encode(name).decode("ascii"),
                    "effective_name_base64": base64.b64encode(effective).decode("ascii"),
                    "native_diverted_destination_collision": collision,
                }
            )
        raw = _input_bytes(files["/var/lib/dpkg/triggers/File"])
        for line in _metadata_lines(raw, deadline):
            _before_cutoff(deadline)
            path, separator, specification = line.partition(b" ")
            if not separator or not path.startswith(b"/"):
                raise ValueError(ERROR_INPUT)
            native_name = _fsys_name(path)
            interests.append(
                {
                    "native_name_base64": base64.b64encode(native_name).decode("ascii"),
                    **_interest_fields(specification),
                    "matches_new_member": native_name in effective_paths,
                }
            )
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"inputs": snapshot, "basis": basis, "routes": result}) from error


def _inventory_instances(host: HostSubstrateFacts, deadline: AdmittedDeadline) -> dict[str, dict[str, JsonObject]]:
    _before_cutoff(deadline)
    raw = base64.b64decode(host.inventory_base64, validate=True)
    if hashlib.sha256(raw).hexdigest() != host.inventory_sha256:
        raise ValueError(ERROR_INPUT)
    instances: dict[str, dict[str, JsonObject]] = {}
    for line in raw.decode("utf-8").splitlines():
        _before_cutoff(deadline)
        fields = line.split("\t")
        if len(fields) != 4:
            raise ValueError(ERROR_INPUT)
        name, version, architecture, status = fields
        state_fields = status.split(" ")
        if (
            PACKAGE_NAME.fullmatch(name) is None
            or (architecture and ARCHITECTURE_NAME.fullmatch(architecture) is None)
            or len(state_fields) != 3
            or state_fields[0] not in PACKAGE_WANTS
            or state_fields[1] not in PACKAGE_ERRORS
            or state_fields[2] not in PACKAGE_STATES
        ):
            raise ValueError(ERROR_INPUT)
        name = name.lower()
        group = instances.setdefault(name, {})
        if architecture in group:
            raise ValueError(ERROR_INPUT)
        group[architecture] = {
            "package_name": name,
            "version": version,
            "architecture": architecture,
            "selection_state": state_fields[0],
            "error_flag": state_fields[1],
            "lifecycle": state_fields[2],
        }
    return instances


def _registered_instance(
    specification: bytes, instances: dict[str, dict[str, JsonObject]]
) -> tuple[JsonObject, tuple[str, str] | None]:
    name, colon, architecture = specification.decode("ascii").partition(":")
    if PACKAGE_NAME.fullmatch(name) is None or (colon and ARCHITECTURE_NAME.fullmatch(architecture) is None):
        raise ValueError(ERROR_INPUT)
    name = name.lower()
    group = instances.get(name, {})
    present = {arch: row for arch, row in group.items() if row["lifecycle"] != "not-installed"}
    if not colon and len(present) > 1:
        # pkg_spec_parse_pkg with ARCH_SINGLE fails for an ambiguous unqualified name, even on an unrelated path.
        raise ValueError(ERROR_INPUT)
    if "" in present:
        # Do not pretend an unknown native architecture is an absent qualified instance.
        return {
            "package_name": name,
            "architecture": architecture if colon else None,
            "identity_state": "unproven_architecture",
            "lifecycle": None,
            "activation_eligible": None
            if any(row["lifecycle"] in ACTIVATION_STATES for row in present.values())
            else False,
        }, None
    if colon:
        row = group.get(architecture)
        if row is None:
            return {
                "package_name": name,
                "architecture": architecture,
                "identity_state": "resolved_qualified_not_installed",
                "lifecycle": "not-installed",
                "activation_eligible": False,
            }, (name, architecture)
    elif present:
        architecture, row = next(iter(present.items()))
    else:
        # The original complete no-pattern query omits not-installed slots. Native available/slot choice is unclaimed.
        return {
            "package_name": name,
            "architecture": None,
            "identity_state": "unproven_inactive_singleton",
            "lifecycle": "not-installed",
            "activation_eligible": False,
        }, None
    return {
        **row,
        "identity_state": "resolved",
        "activation_eligible": row["lifecycle"] in ACTIVATION_STATES,
    }, (name, architecture)


def _interest_instance(
    interest: JsonObject, instances: dict[str, dict[str, JsonObject]]
) -> tuple[JsonObject, tuple[str, str] | None]:
    encoded = interest["package_spec_base64"]
    if not isinstance(encoded, str):
        raise ValueError(ERROR_INPUT)
    return _registered_instance(base64.b64decode(encoded, validate=True), instances)


def interpret_registered_instances(
    routes: JsonObject, explicit: JsonObject, host: HostSubstrateFacts, deadline: AdmittedDeadline
) -> JsonObject:
    """Join original native inventory to registrations; executable-recipient/source/deferred admission remains separate."""
    registrations: list[JsonValue] = []
    explicit_registrations: list[JsonValue] = []
    result: JsonObject = {
        "registrations": registrations,
        "explicit_registrations": explicit_registrations,
        "inventory_sha256": host.inventory_sha256,
        "deferred_and_pending_work": "unproven",
        "recipient_admission": "unproven",
        "error": None,
    }
    try:
        instances = _inventory_instances(host, deadline)
        interests = routes["file_interests"]
        if routes["error"] is not None or not isinstance(interests, list):
            raise ValueError(ERROR_INPUT)
        seen: set[tuple[bytes, tuple[str, str]]] = set()
        for value in interests:
            _before_cutoff(deadline)
            interest = object_value(value)
            native_name = base64.b64decode(text(interest, "native_name_base64"), validate=True)
            if type(interest["matches_new_member"]) is not bool:
                raise ValueError(ERROR_INPUT)
            instance, identity = _interest_instance(interest, instances)
            registrations.append(
                {
                    **interest,
                    "instance": instance,
                    "duplicate_identity": "resolved" if identity is not None else "unproven",
                }
            )
            if identity is not None:
                key = (native_name, identity)
                if key in seen:
                    raise ValueError(ERROR_INPUT)
                seen.add(key)
        sources = explicit["files"]
        if explicit["error"] is not None or not isinstance(sources, list):
            raise ValueError(ERROR_INPUT)
        for source_value in sources:
            _before_cutoff(deadline)
            source = object_value(source_value)
            interests = source["interests"]
            if not isinstance(interests, list):
                raise ValueError(ERROR_INPUT)
            resolved: list[JsonValue] = []
            explicit_registrations.append({"path": source["path"], "present": source["present"], "interests": resolved})
            for value in interests:
                _before_cutoff(deadline)
                interest = object_value(value)
                instance, identity = _interest_instance(interest, instances)
                # trk_explicit_activate_awaiter iterates repeated rows; it has no File-style duplicate rejection.
                resolved.append(
                    {
                        **interest,
                        "instance": instance,
                        "duplicate_identity": "resolved" if identity is not None else "unproven",
                    }
                )
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError(
            {"routes": routes, "explicit": explicit, "inventory_base64": host.inventory_base64, "instances": result}
        ) from error


def _deferred_kind(trigger: bytes) -> str:
    if trigger.startswith(b"/"):
        slash = 0
        while slash >= 0:
            if slash + 1 == len(trigger) or trigger[slash + 1 : slash + 2] == b"/":
                return "unknown"
            slash = trigger.find(b"/", slash + 2)
        return "file"
    if PACKAGE_NAME.fullmatch(trigger.decode("ascii")) is not None and b"_" not in trigger:
        return "explicit"
    # Native unknown activation callbacks are no-ops; this does not validate or ignore their awaiter identities.
    return "unknown"


def _deferred_entry(line: bytes, number: int, entries: list[JsonValue], deadline: AdmittedDeadline) -> None:
    start = len(line) - len(line.lstrip(b" \t"))
    if start == len(line) or line[start : start + 1] == b"#":
        return
    match = VISIBLE_TRIGGER.match(line, start)
    if match is None or match.end() == len(line):
        raise ValueError(ERROR_INPUT)
    trigger = match.group()
    position = match.end() + 1  # Native parser consumes exactly one separator after the visible trigger.
    awaiters: list[JsonValue] = []
    entries.append(
        {
            "native_line": number,
            "trigger_base64": base64.b64encode(trigger).decode("ascii"),
            "kind": _deferred_kind(trigger),
            "awaiters": awaiters,
        }
    )
    while position < len(line):
        _before_cutoff(deadline)
        while position < len(line) and line[position : position + 1] in (b" ", b"\t"):
            position += 1
        match = DEFERRED_PACKAGE.match(line, position)
        if match is None:
            raise ValueError(ERROR_INPUT)
        package = match.group()
        end = match.end()
        if (end < len(line) and line[end : end + 1] not in (b"#", b" ", b"\t")) or (
            package.startswith(b"-") and package != b"-"
        ):
            raise ValueError(ERROR_INPUT)
        awaiters.append(
            {
                "package_spec_base64": base64.b64encode(package).decode("ascii"),
                "null_awaiter": package == b"-",
                "package_identity": "unproven" if package != b"-" else "none",
            }
        )
        position = end + 1


def parse_deferred_inputs(snapshot: JsonObject, deadline: AdmittedDeadline) -> JsonObject:
    """Preserve actual deferred grammar and native default states; recipient/pending/source attribution remains owed."""
    entries: list[JsonValue] = []
    result: JsonObject = {
        "entries": entries,
        "native_state": "unproven",
        "stopped_at_empty_line": False,
        "recipient_and_pending_attribution": "unproven",
        "error": None,
    }
    try:
        _before_cutoff(deadline)
        files = _input_files(snapshot)
        row = files["/var/lib/dpkg/triggers/Unincorp"]
        data = _input_bytes(row)
        result["present"] = row["present"]
        if data is None:
            # Package actions install a transitional hook; absence is not the existing empty-file state.
            result["native_state"] = "absent_native_initialization"
        elif not data:
            result["native_state"] = "empty_no_deferred_work"
        else:
            result["native_state"] = "deferred_records"
            with io.BytesIO(data) as stream:
                number = 0
                while (line := _checked_metadata_line(stream, DEFERRED_LINE_SIZE, deadline)) is not None:
                    # trigdef_parse's >0 loop terminates at a physically empty line, before later input.
                    if not line:
                        result["stopped_at_empty_line"] = True
                        break
                    number += 1
                    _deferred_entry(line, number, entries, deadline)
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"inputs": snapshot, "deferred": result}) from error


def read_explicit_interests(snapshot: JsonObject, deferred: JsonObject, deadline: AdmittedDeadline) -> JsonObject:
    """Read only interest bodies actually used by explicit deferred records; no initialization census or effect."""
    files: list[JsonValue] = []
    requests: list[JsonValue] = []
    result: JsonObject = {
        "scope": "deferred_explicit_records_only",
        "files": files,
        "requests": requests,
        "native_state": None,
        "recipient_admission": "unproven",
        "error": None,
    }
    try:
        _before_cutoff(deadline)
        result["native_state"] = deferred["native_state"]
        existing = _input_files(snapshot)
        entries = deferred["entries"]
        if deferred["error"] is not None or not isinstance(entries, list):
            raise ValueError(ERROR_INPUT)
        indices: dict[str, int] = {}
        for value in entries:
            _before_cutoff(deadline)
            entry = object_value(value)
            if entry["kind"] != "explicit":
                continue
            trigger = base64.b64decode(text(entry, "trigger_base64"), validate=True)
            if _deferred_kind(trigger) != "explicit" or not isinstance(entry["awaiters"], list):
                raise ValueError(ERROR_INPUT)
            path = Path("/var/lib/dpkg/triggers") / trigger.decode("ascii")
            address = str(path)
            request: JsonObject = {
                "trigger_base64": entry["trigger_base64"],
                "native_line": entry["native_line"],
                "path": address,
            }
            requests.append(request)
            if not entry["awaiters"]:
                # Native start can open the name, but no activate_awaiter callback consumes the body.
                request["body_lookup"] = "not_consumed_no_awaiter"
                continue
            if address not in indices:
                indices[address] = len(files)
                if address in existing:
                    files.append(existing[address])
                else:
                    _file(path, deadline, files)
            request["body_lookup"] = "captured"
            request["file_index"] = indices[address]
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"inputs": snapshot, "deferred": deferred, "explicit": result}) from error


def parse_explicit_interests(lookups: JsonObject, deadline: AdmittedDeadline) -> JsonObject:
    """Interpret captured native explicit interest rows, preserving absence, order and duplicates."""
    parsed: list[JsonValue] = []
    result: JsonObject = {
        "files": parsed,
        "requests": None,
        "recipient_admission": "unproven",
        "error": None,
    }
    try:
        _before_cutoff(deadline)
        result["requests"] = lookups["requests"]
        files = lookups["files"]
        if lookups["error"] is not None or not isinstance(files, list):
            raise ValueError(ERROR_INPUT)
        for value in files:
            _before_cutoff(deadline)
            source = object_value(value)
            data = _input_bytes(source)
            interests: list[JsonValue] = []
            parsed.append({"path": source["path"], "present": source["present"], "interests": interests})
            for number, line in enumerate(_metadata_lines(data, deadline), 1):
                _before_cutoff(deadline)
                interests.append({"native_line": number, **_interest_fields(line)})
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError({"lookups": lookups, "interests": result}) from error


def inspect_initialization_compatibility(
    snapshot: JsonObject, host: HostSubstrateFacts, package: StaticPackage, deadline: AdmittedDeadline
) -> JsonObject:
    """Capture one sufficient actual incompatibility witness; never infer compatibility from its absence."""
    files: list[JsonValue] = []
    result: JsonObject = {
        "files": files,
        "scope": "ordinary_writing_container_installation",
        "initialization": "unproven",
        "writing_initialization_compatibility": "unproven",
        "error": None,
    }
    try:
        _before_cutoff(deadline)
        if host.container_installed:
            result["scope"] = "no_container_installation"
            return result
        actual = _input_files(snapshot)
        if _input_bytes(actual["/var/lib/dpkg/triggers/Unincorp"]) is not None:
            result["initialization"] = "not_requested_by_unincorp"
            return result
        result["initialization"] = "absent_native_initialization"
        lock = parse_object(package.lock_bytes)
        scripts = lock["host_maintainer_scripts"]
        final_packages = object_value(lock["host_closure"])["final_packages"]
        if not isinstance(scripts, list) or not isinstance(final_packages, list):
            raise ValueError(ERROR_INPUT)
        controls = [
            object_value(value)
            for value in scripts
            if object_value(value).get("package") == "ca-certificates" and object_value(value).get("file") == "triggers"
        ]
        required = [
            object_value(value) for value in final_packages if object_value(value).get("name") == "ca-certificates"
        ]
        if len(controls) != 1 or len(required) != 1:
            raise ValueError(ERROR_INPUT)
        declared, final = controls[0], required[0]
        instance, identity = _registered_instance(b"ca-certificates", _inventory_instances(host, deadline))
        result["instance"] = instance
        if (
            identity is None
            or instance["identity_state"] != "resolved"
            or instance["version"] != text(declared, "version")
            or instance["version"] != text(final, "version")
            or instance["architecture"] != text(final, "architecture")
            or instance["selection_state"] != "install"
            or instance["error_flag"] != "ok"
            or instance["lifecycle"] != "installed"
        ):
            raise ValueError(ERROR_INPUT)
        # Locked ca-certificates is Multi-Arch: foreign; its native info filename is unqualified.
        path = Path("/var/lib/dpkg/info/ca-certificates.triggers")
        _file(path, deadline, files)
        data = _input_bytes(object_value(files[0]))
        matched = (
            data is not None
            and len(data) == positive_integer(declared, Field.BYTES)
            and hashlib.sha256(data).hexdigest() == text(declared, Field.SHA256)
        )
        result["matches_declared_source"] = matched
        if matched:
            # This exact control declares two interests. Native transitional activation leaves this installed
            # package pending. The permitted container install / named dbus pass cannot settle it.
            result["writing_initialization_compatibility"] = "incompatible"
            result["reason"] = (
                "initialization leaves required ca-certificates pending outside the permitted named dbus pass"
            )
            result["required_status"] = "install ok installed"
            result["predicted_pending_names"] = ["update-ca-certificates", "update-ca-certificates-fresh"]
        _before_cutoff(deadline)
        return result
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        result["error"] = {"error_class": type(error).__name__, "detail": str(error)}
        raise DpkgInputError(
            {"inputs": snapshot, "inventory_base64": host.inventory_base64, "initialization": result}
        ) from error

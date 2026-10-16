"""Fixed guest OS/package and ordinary-account setup after protected namespace admission."""

from __future__ import annotations

import base64
import grp
import hashlib
import os
import pwd
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

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
from tools.ci.enclosure_data import (
    DEB_SUFFIX,
    GUEST_ARCHIVE_DIRECTORY,
    GUEST_TOOL_DIRECTORY,
    READ_BINARY,
    TGZ_SUFFIX,
    NativeCommand,
    _archive,
    _command,
    verify_bootstrap_binaries,
)
from tools.ci.enclosure_guest import ERROR_CONTEXT, SOURCE_ROOT, GuestContext, Role
from tools.ci.enclosure_guest import Key as GuestKey
from tools.ci.enclosure_journal import Controller

SETUP_UNIT: Final = "guest-setup.service"
APT_ARGUMENTS: Final = (
    "/usr/bin/apt-get",
    "--yes",
    "--no-download",
    "--no-remove",
    "--no-install-recommends",
    "-o",
    "Dir::Etc::sourcelist=/dev/null",
    "-o",
    "Dir::Etc::sourceparts=-",
    "-o",
    "Acquire::Retries=0",
    "-o",
    "Dpkg::Use-Pty=0",
    "install",
)
INVENTORY_ARGUMENTS: Final = (
    "/usr/bin/dpkg-query",
    "--show",
    "--showformat=${Package}\t${Version}\t${Architecture}\t${Status}\n",
)
GROUPADD: Final = "/usr/sbin/groupadd"
USERADD: Final = "/usr/sbin/useradd"
LOGINCTL: Final = "/usr/bin/loginctl"
GID_OPTION: Final = "--gid"
UID_OPTION: Final = "--uid"
HOME_OPTION: Final = "--home-dir"
SHELL_OPTION: Final = "--shell"
CREATE_HOME: Final = "--create-home"
ENABLE_LINGER: Final = "enable-linger"
CHOWN: Final = "/usr/bin/chown"
CHOWN_ARGUMENTS: Final = ("--recursive", "--no-dereference")
GIT_DIRECTORY: Final = ".git"
NPM_ARGUMENTS: Final = (
    "/usr/local/bin/npm",
    "install",
    "--global",
    "--offline",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    "--prefix",
    "/usr/local",
)
COREPACK: Final = "corepack"
PRETTIER: Final = "prettier"
PNPM: Final = "pnpm"
COREPACK_COMMAND: Final = "/usr/local/bin/corepack"
COREPACK_ENABLE: Final = (COREPACK_COMMAND, "enable", "--install-directory", "/usr/local/bin")
COREPACK_INSTALL: Final = (COREPACK_COMMAND, "install", "--global", "--cache-only")
COREPACK_HOME: Final = Path("/opt/telec-ra/corepack")
COREPACK_INSTALL_FOLDER: Final = "v1"
COREPACK_METADATA: Final = ".corepack"
NODE_MODULES: Final = Path("/usr/local/lib/node_modules")
TOOL_PREFIX: Final = Path("/usr/local")
PACKAGE_JSON: Final = "package.json"
SHA512: Final = "sha512"
SRI_PREFIX: Final = "sha512-"
HASH_PREFIX: Final = "sha512."
SPEC_SEPARATOR: Final = "@"
BUILD_SEPARATOR: Final = "+"
OWNER_SEPARATOR: Final = ":"
SYSTEMCTL: Final = "/usr/bin/systemctl"
START: Final = "start"
SYSTEM_START: Final = (SYSTEMCTL, START, "dbus.service", "systemd-logind.service")
NETWORK_START: Final = (SYSTEMCTL, START, "systemd-networkd.service", "systemd-resolved.service")
NETWORK_WAIT: Final = (SYSTEMCTL, START, "systemd-networkd-wait-online.service")
USER_UNIT: Final = "user@{uid}.service"
BUSCTL: Final = "/usr/bin/busctl"
JSON_SHORT: Final = "--json=short"
SYSTEM_BUS: Final = "--system"
USER_ADDRESS: Final = "--address=unix:path=/run/user/{uid}/bus"
RUNUSER: Final = "/usr/sbin/runuser"
RUNUSER_USER: Final = "--user"
BUS_CREDENTIALS: Final = (
    "call",
    "org.freedesktop.DBus",
    "/org/freedesktop/DBus",
    "org.freedesktop.DBus",
    "GetConnectionCredentials",
    "s",
    "org.freedesktop.systemd1",
)
SYSTEM_SOCKET: Final = Path("/run/dbus/system_bus_socket")
USER_SOCKET: Final = "/run/user/{uid}/bus"
PROCESS_PID_NS: Final = "/proc/{pid}/ns/pid"
PROCESS_CGROUP_NS: Final = "/proc/{pid}/ns/cgroup"
PROCESS_CGROUP: Final = "/proc/{pid}/cgroup"
UINT32_MAX: Final = 2**32 - 1
UINT_SIGNATURE: Final = "u"
CREDENTIALS_SIGNATURE: Final = "a{sv}"
SUDO_ID: Final = ("/usr/bin/sudo", "--non-interactive", "--", "/usr/bin/id", "--user")
GUEST_ROOT_UID: Final = b"0"
END_OPTIONS: Final = "--"
INSTALLED: Final = "install ok installed"
TAB: Final = "\t"
UTF8: Final = "utf-8"
GUEST_SCHEME: Final = "guest:"
NANOSECONDS: Final = 1_000_000_000
INVENTORY_LIMIT: Final = 1024 * 1024
REQUIRED_SOURCES: Final = frozenset(
    {
        "tools/ci/enclosure_setup.py",
        "tools/ci/enclosure_data.py",
        "tools/ci/enclosure_journal.py",
        "tools/ci/acceptance_package_policy.py",
    }
)
ERROR_INVENTORY: Final = "the native configured guest package inventory is missing or differs from the fixed closure"
ERROR_ACCOUNT: Final = "the created guest account does not match its reviewed identity"
ERROR_BUDGET: Final = "guest setup exhausted the original admitted unit/command/vector/outer allowance"
ERROR_TOOLS: Final = "the fixed guest bootstrap tools or native Corepack cache differ from the reviewed inputs"
ERROR_BUS: Final = "the native guest system/user bus manager credentials or namespace are unavailable or inconsistent"
ERROR_NATIVE_READ: Final = "native guest read was incomplete or failed: {executable}, exit {status}"
SETUP_ENVIRONMENT: Final = {
    "PATH": "/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
    "COREPACK_HOME": str(COREPACK_HOME),
    "COREPACK_DEFAULT_TO_LATEST": "0",
    "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
    "NPM_CONFIG_USERCONFIG": "/dev/null",
    "NPM_CONFIG_GLOBALCONFIG": "/dev/null",
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
}


class Key(StrEnum):
    """The already declared guest package, policy and account fields."""

    GUEST_CLOSURE = "guest_closure"
    FINAL_PACKAGES = "final_packages"
    ARCHIVE_URL = "archive_url"
    NAME = "name"
    VERSION = "version"
    ARCHITECTURE = "architecture"
    GUEST = "guest"
    ACCOUNT = "account"
    UID = "uid"
    GID = "gid"
    HOME = "home"
    SHELL = "shell"
    PACKAGE_SERVICE_POLICY = "package_service_policy"
    PROSPECTIVE_SOURCE = "prospective_source"
    INSTALLED_PATH = "installed_path"
    NPM_TOOLS = "npm_tools"
    PACKAGE = "package"
    INTEGRITY = "integrity"
    HASH = "hash"
    LOCATOR = "locator"
    REFERENCE = "reference"
    TYPE = "type"
    DATA = "data"
    UNIX_UID = "UnixUserID"
    PROCESS_ID = "ProcessID"


@dataclass(frozen=True)
class NativeRead:
    """Bounded stdout from the real native read; incomplete output cannot prove inventory."""

    status: int | None
    stdout: bytes
    complete: bool


type NativeQuery = Callable[[tuple[str, ...], float], NativeRead]


@dataclass(frozen=True)
class GuestManagerFacts:
    """Native guest-bus ownership and process placement at the stated capture point, not P4 continuity."""

    uid: int
    pid: int
    start_ticks: int
    pid_namespace: str
    cgroup_namespace: str
    cgroup: str
    observed_ns: int


@dataclass(frozen=True)
class GuestOSFacts:
    """Configured package/account/tools and captured native manager facts, without an application verdict."""

    inventory_sha256: str
    account: str
    uid: int
    gid: int
    home: str
    shell: str
    bootstrap_archive_digests: tuple[str, ...]
    corepack_metadata_sha256: str
    system_manager: GuestManagerFacts
    user_manager: GuestManagerFacts


def _query_native(argv: tuple[str, ...], query: NativeQuery, deadline: AdmittedDeadline, cap: int) -> bytes:
    end = deadline.command_end(cap)
    remaining = (end - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(ERROR_BUDGET)
    result = query(argv, remaining)
    if time.monotonic_ns() >= end:
        raise TimeoutError(ERROR_BUDGET)
    if result.status != 0 or not result.complete or len(result.stdout) > INVENTORY_LIMIT:
        raise ValueError(ERROR_NATIVE_READ.format(executable=argv[0], status=result.status))
    return result.stdout


def _credential(credentials: JsonObject, key: Key) -> int:
    # Native busctl preserves the variant's wire type and scalar value in its JSON representation.
    value = credentials.get(key)
    if not isinstance(value, dict) or value.get(Key.TYPE) != UINT_SIGNATURE:
        raise ValueError(ERROR_BUS)
    number = value.get(Key.DATA)
    if type(number) is not int or not 0 <= number <= UINT32_MAX:
        raise ValueError(ERROR_BUS)
    return number


def _manager_facts(
    context: GuestContext,
    argv: tuple[str, ...],
    socket: Path,
    expected_uid: int,
    query: NativeQuery,
    deadline: AdmittedDeadline,
    cap: int,
) -> GuestManagerFacts:
    raw = _query_native(argv, query, deadline, cap)
    response = parse_object(raw)
    body = response.get(Key.DATA)
    if response.get(Key.TYPE) != CREDENTIALS_SIGNATURE or not isinstance(body, list) or len(body) != 1:
        raise ValueError(ERROR_BUS)
    credentials = object_value(body[0])
    uid, pid = _credential(credentials, Key.UNIX_UID), _credential(credentials, Key.PROCESS_ID)
    identity = Controller.capture(pid)
    socket_status = socket.lstat()
    pid_namespace = os.readlink(PROCESS_PID_NS.format(pid=pid))
    cgroup_namespace = os.readlink(PROCESS_CGROUP_NS.format(pid=pid))
    if (
        uid != expected_uid
        or identity.uid != expected_uid
        or (expected_uid == 0 and pid != 1)
        or (expected_uid != 0 and pid <= 1)
        or identity.boot_id != text(context.record, GuestKey.GUEST_BOOT_ID)
        or pid_namespace != text(context.record, GuestKey.PID_NAMESPACE)
        or cgroup_namespace != text(context.record, GuestKey.CGROUP_NAMESPACE)
        or not stat.S_ISSOCK(socket_status.st_mode)
        or socket_status.st_uid != expected_uid
    ):
        raise ValueError(ERROR_BUS)
    with Path(PROCESS_CGROUP.format(pid=pid)).open(encoding=UTF8) as handle:
        cgroup = handle.read(INVENTORY_LIMIT + 1)
    if not cgroup or len(cgroup) > INVENTORY_LIMIT or time.monotonic_ns() >= deadline.effective_end():
        raise ValueError(ERROR_BUS)
    return GuestManagerFacts(
        uid, pid, identity.start_ticks, pid_namespace, cgroup_namespace, cgroup, time.monotonic_ns()
    )


def _verify_inventory(package: StaticPackage, raw: bytes) -> str:
    rows = object_value(parse_object(package.lock_bytes)[Key.GUEST_CLOSURE])[Key.FINAL_PACKAGES]
    if not isinstance(rows, list) or len(raw) > INVENTORY_LIMIT:
        raise ValueError(ERROR_INVENTORY)
    expected: dict[tuple[str, str], str] = {}
    for value in rows:
        row = object_value(value)
        key = (text(row, Key.NAME), text(row, Key.ARCHITECTURE))
        if key in expected:
            raise ValueError(ERROR_INVENTORY)
        expected[key] = text(row, Key.VERSION)
    actual: dict[tuple[str, str], str] = {}
    for line in raw.decode(UTF8).splitlines():
        fields = line.split(TAB)
        if len(fields) != 4 or fields[3] != INSTALLED:
            raise ValueError(ERROR_INVENTORY)
        name, version, architecture, _ = fields
        key = (name, architecture)
        if key in actual:
            raise ValueError(ERROR_INVENTORY)
        actual[key] = version
    if actual != expected:
        raise ValueError(ERROR_INVENTORY)
    return hashlib.sha256(raw).hexdigest()


def _configure_bootstrap_tools(
    context: GuestContext, run: NativeCommand, deadline: AdmittedDeadline, cap: int
) -> tuple[tuple[str, ...], str]:
    verify_bootstrap_binaries(context.package, TOOL_PREFIX, deadline)
    rows = parse_object(context.package.lock_bytes)[Key.NPM_TOOLS]
    if not isinstance(rows, list):
        raise ValueError(ERROR_TOOLS)
    packages: dict[str, tuple[Path, str, str]] = {}
    pnpm_hash = None
    for value in rows:
        row = object_value(value)
        name = text(row, Key.PACKAGE)
        if name not in (COREPACK, PRETTIER, PNPM) or name in packages:
            raise ValueError(ERROR_TOOLS)
        digest = text(row, Field.SHA256)
        archive = _archive(row, {digest: GUEST_TOOL_DIRECTORY / (digest + TGZ_SUFFIX)}, deadline)
        integrity = text(row, Key.INTEGRITY)
        if not integrity.startswith(SRI_PREFIX):
            raise ValueError(ERROR_TOOLS)
        expected = base64.b64decode(integrity[len(SRI_PREFIX) :], validate=True)
        with archive.open(mode=READ_BINARY) as handle:
            actual = hashlib.file_digest(handle, SHA512).digest()
        if len(expected) != 64 or actual != expected:
            raise ValueError(ERROR_TOOLS)
        packages[name] = (archive, text(row, Key.VERSION), digest)
        if name == PNPM:
            pnpm_hash = HASH_PREFIX + expected.hex()
    if set(packages) != {COREPACK, PRETTIER, PNPM} or pnpm_hash is None:
        raise ValueError(ERROR_TOOLS)
    _command((*NPM_ARGUMENTS, str(packages[COREPACK][0]), str(packages[PRETTIER][0])), run, deadline, cap)
    for name in (COREPACK, PRETTIER):
        metadata = parse_object((NODE_MODULES / name / PACKAGE_JSON).read_bytes())
        if metadata.get(Key.NAME) != name or metadata.get(Key.VERSION) != packages[name][1]:
            raise ValueError(ERROR_TOOLS)
    _command(COREPACK_ENABLE, run, deadline, cap)
    reference = packages[PNPM][1] + BUILD_SEPARATOR + pnpm_hash
    # Native Corepack owns its cache format; its exact-version/SRI path does not resolve a floating version.
    _command((*COREPACK_INSTALL, PNPM + SPEC_SEPARATOR + reference), run, deadline, cap)
    metadata_path = COREPACK_HOME / COREPACK_INSTALL_FOLDER / PNPM / packages[PNPM][1] / COREPACK_METADATA
    raw = metadata_path.read_bytes()
    metadata = parse_object(raw)
    locator = object_value(metadata[Key.LOCATOR])
    if metadata.get(Key.HASH) != pnpm_hash or locator.get(Key.NAME) != PNPM or locator.get(Key.REFERENCE) != reference:
        raise ValueError(ERROR_TOOLS)
    if metadata_path.stat().st_uid != 0 or COREPACK_HOME.stat().st_uid != 0:
        raise ValueError(ERROR_TOOLS)
    return tuple(packages[name][2] for name in (COREPACK, PRETTIER, PNPM)), hashlib.sha256(raw).hexdigest()


def configure_guest_os(context: GuestContext, run: NativeCommand, query: NativeQuery) -> GuestOSFacts:
    """Configure exact guest packages/tools, create the declared account/source owner and request native linger."""
    if os.geteuid() != 0:
        raise ValueError(ERROR_CONTEXT)
    context.verify(Role.GUEST_SETUP)
    if not REQUIRED_SOURCES <= set(object_value(context.record[GuestKey.SOURCE_FILES])):
        raise ValueError(ERROR_CONTEXT)
    original = context.admitted_deadline()
    deadline = AdmittedDeadline(original.outer_end_ns, original.vector_end_ns, context.command_end(SETUP_UNIT))
    recipe = parse_object(context.package.recipe_bytes)
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    guest = object_value(recipe[Key.GUEST])
    policy = object_value(guest[Key.PACKAGE_SERVICE_POLICY])
    # This policy remains installed through package configuration and is removed only before the real product installer.
    installed_policy = Path(text(policy, Key.INSTALLED_PATH).removeprefix(GUEST_SCHEME))
    expected_policy = SOURCE_ROOT / text(policy, Key.PROSPECTIVE_SOURCE)
    policy_status = installed_policy.lstat()
    if (
        not stat.S_ISREG(policy_status.st_mode)
        or policy_status.st_uid != 0
        or stat.S_IMODE(policy_status.st_mode) & 0o022
        or not stat.S_IMODE(policy_status.st_mode) & 0o111
        or installed_policy.read_bytes() != expected_policy.read_bytes()
    ):
        raise ValueError(ERROR_CONTEXT)
    rows = object_value(parse_object(context.package.lock_bytes)[Key.GUEST_CLOSURE])[Key.FINAL_PACKAGES]
    if not isinstance(rows, list):
        raise ValueError(ERROR_INVENTORY)
    archives: list[str] = []
    for value in rows:
        row = object_value(value)
        if Key.ARCHIVE_URL in row:
            digest = text(row, Field.SHA256)
            archive = GUEST_ARCHIVE_DIRECTORY / (digest + DEB_SUFFIX)
            archives.append(str(_archive(row, {digest: archive}, deadline)))
    _command((*APT_ARGUMENTS, *archives), run, deadline, cap)
    inventory_digest = _verify_inventory(context.package, _query_native(INVENTORY_ARGUMENTS, query, deadline, cap))
    _command(NETWORK_START, run, deadline, cap)
    _command(NETWORK_WAIT, run, deadline, cap)
    bootstrap_digests, corepack_metadata_digest = _configure_bootstrap_tools(context, run, deadline, cap)
    account = object_value(guest[Key.ACCOUNT])
    name = text(account, Key.NAME)
    uid, gid = positive_integer(account, Key.UID), positive_integer(account, Key.GID)
    home, shell = text(account, Key.HOME), text(account, Key.SHELL)
    _command((GROUPADD, GID_OPTION, str(gid), END_OPTIONS, name), run, deadline, cap)
    _command(
        (
            USERADD,
            CREATE_HOME,
            UID_OPTION,
            str(uid),
            GID_OPTION,
            str(gid),
            HOME_OPTION,
            home,
            SHELL_OPTION,
            shell,
            END_OPTIONS,
            name,
        ),
        run,
        deadline,
        cap,
    )
    found, group = pwd.getpwnam(name), grp.getgrnam(name)
    if (found.pw_uid, found.pw_gid, found.pw_dir, found.pw_shell, group.gr_gid) != (uid, gid, home, shell, gid):
        raise ValueError(ERROR_ACCOUNT)
    # Existing full-profile source reads and shared clones run as this same ordinary account.
    _command(
        (CHOWN, *CHOWN_ARGUMENTS, str(uid) + OWNER_SEPARATOR + str(gid), END_OPTIONS, str(SOURCE_ROOT)),
        run,
        deadline,
        cap,
    )
    if any(
        (path.stat().st_uid, path.stat().st_gid) != (uid, gid) for path in (SOURCE_ROOT, SOURCE_ROOT / GIT_DIRECTORY)
    ):
        raise ValueError(ERROR_ACCOUNT)
    _command(SYSTEM_START, run, deadline, cap)
    _command((LOGINCTL, ENABLE_LINGER, END_OPTIONS, name), run, deadline, cap)
    # Native start waits for the existing or newly admitted user-manager job; it never retries an unknown result.
    _command((SYSTEMCTL, START, USER_UNIT.format(uid=uid)), run, deadline, cap)
    if (
        _query_native((RUNUSER, RUNUSER_USER, name, END_OPTIONS, *SUDO_ID), query, deadline, cap).strip()
        != GUEST_ROOT_UID
    ):
        raise ValueError(ERROR_ACCOUNT)
    system_manager = _manager_facts(
        context,
        (BUSCTL, JSON_SHORT, SYSTEM_BUS, *BUS_CREDENTIALS),
        SYSTEM_SOCKET,
        0,
        query,
        deadline,
        cap,
    )
    user_manager = _manager_facts(
        context,
        (RUNUSER, RUNUSER_USER, name, END_OPTIONS, BUSCTL, JSON_SHORT, USER_ADDRESS.format(uid=uid), *BUS_CREDENTIALS),
        Path(USER_SOCKET.format(uid=uid)),
        uid,
        query,
        deadline,
        cap,
    )
    return GuestOSFacts(
        inventory_digest,
        name,
        uid,
        gid,
        home,
        shell,
        bootstrap_digests,
        corepack_metadata_digest,
        system_manager,
        user_manager,
    )

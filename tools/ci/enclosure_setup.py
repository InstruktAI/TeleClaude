"""Fixed guest OS/package and ordinary-account setup after protected namespace admission."""

from __future__ import annotations

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
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_data import DEB_SUFFIX, GUEST_ARCHIVE_DIRECTORY, NativeCommand, _archive, _command
from tools.ci.enclosure_guest import ERROR_CONTEXT, SOURCE_ROOT, GuestContext
from tools.ci.enclosure_guest import Key as GuestKey

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
END_OPTIONS: Final = "--"
INSTALLED: Final = "install ok installed"
TAB: Final = "\t"
UTF8: Final = "utf-8"
GUEST_SCHEME: Final = "guest:"
NANOSECONDS: Final = 1_000_000_000
INVENTORY_LIMIT: Final = 1024 * 1024
REQUIRED_SOURCES: Final = frozenset(
    {"tools/ci/enclosure_setup.py", "tools/ci/enclosure_data.py", "tools/ci/acceptance_package_policy.py"}
)
ERROR_INVENTORY: Final = "the native configured guest package inventory is missing or differs from the fixed closure"
ERROR_ACCOUNT: Final = "the created guest account does not match its reviewed identity"
ERROR_BUDGET: Final = "guest setup exhausted the original admitted unit/command/vector/outer allowance"
SETUP_ENVIRONMENT: Final = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
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


@dataclass(frozen=True)
class NativeRead:
    """Bounded stdout from the real native read; incomplete output cannot prove inventory."""

    status: int | None
    stdout: bytes
    complete: bool


type NativeQuery = Callable[[tuple[str, ...], float], NativeRead]


@dataclass(frozen=True)
class GuestOSFacts:
    """Configured package/account facts, without a tool, bus, payload or application verdict."""

    inventory_sha256: str
    account: str
    uid: int
    gid: int
    home: str
    shell: str


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


def configure_guest_os(context: GuestContext, run: NativeCommand, query: NativeQuery) -> GuestOSFacts:
    """Configure only staged exact packages, create the declared account and request native linger."""
    if os.geteuid() != 0:
        raise ValueError(ERROR_CONTEXT)
    context.verify()
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
    end = deadline.command_end(cap)
    remaining = (end - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(ERROR_BUDGET)
    inventory = query(INVENTORY_ARGUMENTS, remaining)
    if time.monotonic_ns() >= end:
        raise TimeoutError(ERROR_BUDGET)
    if inventory.status != 0 or not inventory.complete:
        raise ValueError(ERROR_INVENTORY)
    inventory_digest = _verify_inventory(context.package, inventory.stdout)
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
    _command((LOGINCTL, ENABLE_LINGER, END_OPTIONS, name), run, deadline, cap)
    return GuestOSFacts(inventory_digest, name, uid, gid, home, shell)

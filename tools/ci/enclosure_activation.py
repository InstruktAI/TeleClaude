"""Finite native source reads before owned starts and admission sealing."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_actions import Template
from tools.ci.enclosure_configuration import VENDOR_TEMPLATE
from tools.ci.enclosure_configuration import Key as ConfigurationKey
from tools.ci.enclosure_contract import (
    Action,
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    Parameter,
    StaticPackage,
    object_value,
    parse_object,
    text,
)
from tools.ci.enclosure_graph import DependencyGraph
from tools.ci.enclosure_host import Key as HostKey
from tools.ci.enclosure_host import Kind, _locked_file
from tools.ci.enclosure_manager import ManagerRead
from tools.ci.enclosure_owner import Key as OwnerKey
from tools.ci.enclosure_owner import RunOwner

ROOT: Final = Path("/")
LINK_SUFFIXES: Final = (".wants", ".requires", ".upholds")
INSTANCE_SEPARATOR: Final = "@"
DASH: Final = "-"
DOT: Final = "."
DROP_IN_SUFFIX: Final = ".d"
CONFIG_SUFFIX: Final = ".conf"
SETTINGS_SUFFIX: Final = ".nspawn"
SETTINGS_DIRECTORIES: Final = (Path("/etc/systemd/nspawn"), Path("/run/systemd/nspawn"))
PARENT_ANCESTORS: Final = frozenset({"-.slice", "tc.slice", "tc-ra.slice"})
ERROR_CENSUS: Final = "native activation sources are unreadable, changed, unprotected or outside the original allowance"


class Key(StrEnum):
    """Finite source observations; no host-admission or future-creator claim is encoded here."""

    DIRECTORIES = "directories"
    LINKS = "links"
    ALIASES = "aliases"
    UNCLASSIFIED = "unclassified"
    PRESENT = "present"
    DEVICE = "device"
    INODE = "inode"
    MODE = "mode"
    UID = "uid"
    MTIME_NS = "mtime_ns"
    CTIME_NS = "ctime_ns"
    MANAGER_SEQUENCE = "manager_sequence"
    MANAGER_VERSION = "manager_version"
    MANAGER_OBSERVED_NS = "manager_observed_ns"
    UNIT_PATHS = "unit_paths"
    OBSERVED_NS = "observed_ns"
    ACTION = "action"
    UNIT_DESTINATIONS = "unit_destinations"
    SOURCES = "sources"
    SETTINGS = "settings"
    BEGIN_SEQUENCE = "begin_sequence"


@dataclass(frozen=True)
class Entry:
    """One lstat/readlink through a held directory descriptor."""

    name: str
    mode: int
    uid: int
    target: str | None


@dataclass(frozen=True)
class ActivationSources:
    """Actual finite link-source facts; unclassified entries remain blocking for ensuing sealing."""

    directories: tuple[JsonObject, ...]
    links: tuple[JsonObject, ...]
    aliases: tuple[JsonObject, ...]
    unclassified: tuple[str, ...]
    manager_version: str
    unit_paths: tuple[str, ...]
    manager_sequence: int
    manager_observed_ns: int
    observed_ns: int

    def record(self) -> JsonObject:
        """Keep facts separate from native job settlement, helper closure and the eventual seal."""
        return {
            Key.DIRECTORIES: list[JsonValue](self.directories),
            Key.LINKS: list[JsonValue](self.links),
            Key.ALIASES: list[JsonValue](self.aliases),
            Key.UNCLASSIFIED: list[JsonValue](self.unclassified),
            Key.MANAGER_VERSION: self.manager_version,
            Key.UNIT_PATHS: list[JsonValue](self.unit_paths),
            Key.MANAGER_SEQUENCE: self.manager_sequence,
            Key.MANAGER_OBSERVED_NS: self.manager_observed_ns,
            Key.OBSERVED_NS: self.observed_ns,
        }


def _time(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_CENSUS)


def _directory(path: Path, deadline: AdmittedDeadline) -> tuple[JsonObject, tuple[Entry, ...]]:
    _time(deadline)
    physical = path.resolve(strict=False)
    for ancestor in (path, *path.parents, physical, *physical.parents):
        try:
            native = ancestor.lstat()
        except FileNotFoundError:
            continue
        if native.st_uid != 0 or (not stat.S_ISLNK(native.st_mode) and native.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ValueError(ERROR_CENSUS)
    try:
        descriptor = os.open(physical, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return {Field.PATH: str(path), Key.PRESENT: False}, ()
    try:
        before = os.fstat(descriptor)
        result: list[Entry] = []
        with os.scandir(descriptor) as entries:
            for entry in entries:
                _time(deadline)
                original = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                target = os.readlink(entry.name, dir_fd=descriptor) if stat.S_ISLNK(original.st_mode) else None
                after = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                if (
                    original.st_dev,
                    original.st_ino,
                    original.st_mode,
                    original.st_uid,
                    original.st_mtime_ns,
                    original.st_ctime_ns,
                ) != (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError(ERROR_CENSUS)
                result.append(Entry(entry.name, original.st_mode, original.st_uid, target))
        after_directory = os.fstat(descriptor)
        linked = path.stat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
            after_directory.st_dev,
            after_directory.st_ino,
            after_directory.st_mtime_ns,
            after_directory.st_ctime_ns,
        ) or (before.st_dev, before.st_ino) != (linked.st_dev, linked.st_ino):
            raise ValueError(ERROR_CENSUS)
        _time(deadline)
        return {
            Field.PATH: str(physical),
            Key.PRESENT: True,
            Key.DEVICE: before.st_dev,
            Key.INODE: before.st_ino,
            Key.MTIME_NS: before.st_mtime_ns,
            Key.CTIME_NS: before.st_ctime_ns,
        }, tuple(sorted(result, key=lambda item: item.name))
    finally:
        os.close(descriptor)


def _address(path: Path) -> Path:
    # Preserve a symlink's leaf address; resolve only its directory (including the distro's usr-merge aliases).
    return path.parent.resolve(strict=False) / path.name


def _targets_owned(path: Path, owned_names: frozenset[str], deadline: AdmittedDeadline) -> bool:
    seen: set[Path] = set()
    while True:
        _time(deadline)
        path = _address(path)
        if path.name in owned_names:
            return True
        if path in seen:
            # A native symlink loop cannot resolve a different target; it is not an alias to the owned unit.
            return False
        seen.add(path)
        try:
            before = path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISLNK(before.st_mode):
            return False
        target = Path(os.readlink(path))
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError(ERROR_CENSUS)
        path = target if target.is_absolute() else path.parent / target


def _dependency_names(name: str) -> frozenset[str]:
    """Follow v255 unit_file_find_dirs: instance/template, prefix hierarchy and common unit type."""
    found: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        stem, separator, unit_type = current.rpartition(DOT)
        if not stem or not separator or not unit_type or Path(current).name != current:
            raise ValueError(ERROR_CENSUS)
        found.add(unit_type)
        prefix, instance_separator, instance = stem.partition(INSTANCE_SEPARATOR)
        is_instance = bool(instance_separator and instance)
        if is_instance:
            pending.append(prefix + INSTANCE_SEPARATOR + DOT + unit_type)
        # Native lookup skips a trailing dash once before finding the next prefix boundary.
        shortened = prefix[:-1] if prefix.endswith(DASH) else prefix
        dash = shortened.rfind(DASH)
        if dash > 0:
            next_prefix = shortened[: dash + 1]
            next_instance = INSTANCE_SEPARATOR + instance if is_instance else ""
            pending.append(next_prefix + next_instance + DOT + unit_type)
    return frozenset(found)


def _scope(graph: DependencyGraph, owned_names: frozenset[str]) -> tuple[frozenset[str], frozenset[str]]:
    if not owned_names or any(Path(name).name != name for name in owned_names):
        raise ValueError(ERROR_CENSUS)
    names: set[str] = set()
    critical_names = set(owned_names)
    for node in graph.nodes:
        aliases = node.read.unit.get(ConfigurationKey.NAMES)
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias for alias in aliases):
            raise ValueError(ERROR_CENSUS)
        for name in (node.read.name, *aliases):
            if not isinstance(name, str):
                raise ValueError(ERROR_CENSUS)
            names.update(_dependency_names(name))
        if node.read.name not in owned_names:
            continue
        fragment = node.read.unit.get(ConfigurationKey.FRAGMENT_PATH)
        if isinstance(fragment, str) and fragment:
            critical_names.add(Path(fragment).name)
        mounts = node.read.unit.get(ConfigurationKey.REQUIRES_MOUNTS_FOR)
        if not isinstance(mounts, list) or any(not isinstance(value, str) for value in mounts):
            raise ValueError(ERROR_CENSUS)
        critical_names.update(Path(value).name for value in mounts if isinstance(value, str))
    return frozenset(critical_names), frozenset(name + suffix for name in names for suffix in LINK_SUFFIXES)


def _known_sources(package: StaticPackage) -> dict[Path, JsonObject]:
    rows = parse_object(package.lock_bytes)[HostKey.ACTIVATION_SOURCES]
    if not isinstance(rows, list):
        raise ValueError(ERROR_CENSUS)
    return {
        _address(ROOT / text(row, Field.PATH)): row
        for value in rows
        if (row := object_value(value)).get(HostKey.SCOPE) == HostKey.HOST
    }


def inspect_start_sources(
    owner: RunOwner, package: StaticPackage, manager: ManagerRead, action: Action, deadline: AdmittedDeadline
) -> JsonObject:
    """Read the owned start's fragment/drop-in/link/settings inputs before the separate helper creates or starts it."""
    _time(deadline)
    if action not in (Action.CREATE_PARENT, Action.START_GUEST):
        raise ValueError(ERROR_CENSUS)
    record = parse_object(owner.manifest_bytes)
    parent = text(record, OwnerKey.PARENT_UNIT)
    guest = text(record, OwnerKey.GUEST_UNIT)
    rootfs = Path(text(record, OwnerKey.ROOTFS))
    critical = frozenset({parent, guest, Path(VENDOR_TEMPLATE).name, *PARENT_ANCESTORS})
    relevant = {
        name + suffix
        for unit in critical
        for name in _dependency_names(unit)
        for suffix in (*LINK_SUFFIXES, DROP_IN_SUFFIX)
    }
    known = _known_sources(package)
    parameters: dict[str, str] = {Parameter.RUN_TOKEN: owner.journal.binding.run_token}
    destinations = object_value(parse_object(package.recipe_bytes)[Key.UNIT_DESTINATIONS])
    parent_path = Path(text(destinations, Template.PARENT).format_map(parameters))
    vendor_path = _address(ROOT / VENDOR_TEMPLATE)
    allowed_fragments = {vendor_path}
    if action is Action.START_GUEST:
        data = package.render(
            run_token=owner.journal.binding.run_token,
            candidate_sha=owner.journal.binding.candidate_commit,
            candidate_tree=owner.journal.binding.candidate_tree,
            selection="",
        )[Template.PARENT]
        known[_address(parent_path)] = {
            Field.PATH: str(parent_path.relative_to(ROOT)),
            Field.SHA256: hashlib.sha256(data).hexdigest(),
            Field.BYTES: len(data),
            HostKey.KIND: Kind.FILE.value,
        }
        allowed_fragments.add(_address(parent_path))
    directories: list[JsonValue] = []
    sources: list[JsonValue] = []
    settings: list[JsonValue] = []
    unknown: set[str] = set()
    seen_fragments: set[Path] = set()
    visited: set[Path] = set()
    for root in manager.unit_paths:
        path = Path(root)
        if not path.is_absolute():
            raise ValueError(ERROR_CENSUS)
        canonical = path.resolve(strict=False)
        if canonical in visited:
            continue
        visited.add(canonical)
        directory, entries = _directory(path, deadline)
        directories.append(directory)
        for entry in entries:
            address = canonical / entry.name
            if entry.name in critical:
                row = known.get(address)
                if address not in allowed_fragments or row is None:
                    unknown.add(str(address))
                else:
                    _locked_file(row, deadline)
                    seen_fragments.add(address)
                    sources.append(dict(row))
            elif entry.target is not None and _targets_owned(address, critical, deadline):
                unknown.add(str(address))
            if entry.name not in relevant:
                continue
            if not stat.S_ISDIR(entry.mode):
                unknown.add(str(address))
                continue
            fact, children = _directory(address, deadline)
            directories.append(fact)
            drop_in = entry.name.endswith(DROP_IN_SUFFIX)
            for child in children:
                if drop_in and not child.name.endswith(CONFIG_SUFFIX):
                    continue
                child_path = address / child.name
                row = known.get(child_path)
                sources.append({Field.PATH: str(child_path), HostKey.TARGET: child.target})
                expected = Kind.FILE if drop_in else Kind.SYMLINK
                if row is None or row.get(HostKey.KIND) != expected:
                    unknown.add(str(child_path))
                else:
                    _locked_file(row, deadline)
    unknown.update(str(path) for path in allowed_fragments - seen_fragments)
    # All three native settings locations must be free for the one new runtime file created by start-guest.
    settings_name = rootfs.name + SETTINGS_SUFFIX
    for directory_path in (*SETTINGS_DIRECTORIES, rootfs.parent):
        directory, entries = _directory(directory_path, deadline)
        directories.append(directory)
        for entry in entries:
            if entry.name == settings_name:
                address = directory_path / entry.name
                settings.append({Field.PATH: str(address), HostKey.TARGET: entry.target})
                unknown.add(str(address))
    _time(deadline)
    return {
        Key.ACTION: action.value,
        Key.DIRECTORIES: directories,
        Key.SOURCES: sources,
        Key.SETTINGS: settings,
        Key.UNCLASSIFIED: list[JsonValue](sorted(unknown)),
        Key.MANAGER_VERSION: manager.version,
        Key.UNIT_PATHS: list[JsonValue](manager.unit_paths),
        Key.BEGIN_SEQUENCE: manager.begin_sequence,
        Key.MANAGER_SEQUENCE: manager.sequence,
        Key.MANAGER_OBSERVED_NS: manager.observed_ns,
        Key.OBSERVED_NS: time.monotonic_ns(),
    }


def inspect_activation_sources(
    package: StaticPackage,
    graph: DependencyGraph,
    manager: ManagerRead,
    owned_names: frozenset[str],
    deadline: AdmittedDeadline,
) -> ActivationSources:
    """Inspect each manager unit-path root once and each relevant native activation directory once."""
    _time(deadline)
    critical_names, relevant = _scope(graph, owned_names)
    known = _known_sources(package)
    directories: list[JsonObject] = []
    links: list[JsonObject] = []
    aliases: list[JsonObject] = []
    unknown: set[str] = set()
    visited: set[Path] = set()
    for root in manager.unit_paths:
        _time(deadline)
        path = Path(root)
        if not path.is_absolute():
            raise ValueError(ERROR_CENSUS)
        canonical = path.resolve(strict=False)
        if canonical in visited:
            continue
        visited.add(canonical)
        fact, entries = _directory(path, deadline)
        directories.append(fact)
        for entry in entries:
            address = canonical / entry.name
            if entry.target is not None and entry.name not in owned_names:
                if _targets_owned(address, critical_names, deadline):
                    aliases.append({Field.PATH: str(address), HostKey.TARGET: entry.target})
                    unknown.add(str(address))
            if entry.name not in relevant:
                continue
            if not stat.S_ISDIR(entry.mode) or entry.uid != 0 or entry.mode & (stat.S_IWGRP | stat.S_IWOTH):
                unknown.add(str(address))
                continue
            directory, children = _directory(address, deadline)
            directories.append(directory)
            for child in children:
                child_path = address / child.name
                row = known.get(_address(child_path))
                fact: JsonObject = {
                    Field.PATH: str(child_path),
                    Key.MODE: child.mode,
                    Key.UID: child.uid,
                    HostKey.TARGET: child.target,
                }
                links.append(fact)
                if row is None or not stat.S_ISLNK(child.mode) or row.get(HostKey.KIND) != Kind.SYMLINK:
                    unknown.add(str(child_path))
                    continue
                _locked_file(row, deadline)
    _time(deadline)
    return ActivationSources(
        tuple(directories),
        tuple(links),
        tuple(aliases),
        tuple(sorted(unknown)),
        manager.version,
        manager.unit_paths,
        manager.sequence,
        manager.observed_ns,
        time.monotonic_ns(),
    )

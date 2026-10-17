"""Finite native dependency/source census before host start admission can be sealed."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_configuration import InstanceConfiguration, MaskedInstanceConfiguration
from tools.ci.enclosure_configuration import Key as ConfigurationKey
from tools.ci.enclosure_contract import (
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    StaticPackage,
    object_value,
    parse_object,
    text,
)
from tools.ci.enclosure_host import Key as HostKey
from tools.ci.enclosure_host import Kind, _locked_file
from tools.ci.enclosure_manager import UNIT_REFERENCE_PROPERTIES, AcceptedJob, JobRead, ManagerObserver, UnitRead
from tools.ci.enclosure_population import Invalidation

ROOT: Final = Path("/")
UNIT_DIRECTORY: Final = Path("usr/lib/systemd/system")
EMPTY: Final = ""
LOADED: Final = "loaded"
NATIVE_SLICES: Final = frozenset({"-.slice", "system.slice", "tc.slice", "tc-ra.slice"})
ROOT_MOUNT: Final = "-.mount"
MOUNTINFO: Final = "/proc/self/mountinfo"
# Follow start/trigger creation. PartOf and ordering endpoints stay metadata: starting this unit does not start them.
CREATION_EDGES: Final = (
    "Requires",
    "Wants",
    "BindsTo",
    "Upholds",
    "OnSuccess",
    "OnFailure",
    "Triggers",
)
ROOT_ACTIVATORS: Final = (
    "RequiredBy",
    "WantedBy",
    "RequisiteOf",
    "BoundBy",
    "UpheldBy",
    "TriggeredBy",
    "OnSuccessOf",
    "OnFailureOf",
)
INSTANCE_SEPARATOR: Final = "@"
UNIT_FIELDS: Final = (
    "Id",
    "Names",
    "LoadState",
    "ActiveState",
    "FragmentPath",
    "SourcePath",
    "DropInPaths",
    "Transient",
    "NeedDaemonReload",
    "Job",
    *UNIT_REFERENCE_PROPERTIES,
)
ERROR_GRAPH: Final = "the original native dependency/source census is malformed, late or inconsistent"


class SourceKind(StrEnum):
    """Classification of actual source facts; unclassified nodes never become seal evidence."""

    LOCKED = "locked-vendor-unit"
    RECIPE = "owned-recipe-unit"
    MASKED = "owned-masked-instance"
    MANAGER_NATIVE = "native-manager-unit"
    UNCLASSIFIED = "unclassified"


class Key(StrEnum):
    """Positioned native facts and exact source identities, separate from admission or P4."""

    NODES = "nodes"
    SOURCE_KIND = "source_kind"
    SOURCES = "sources"
    NAME = "name"
    OBJECT_PATH = "object_path"
    UNIT = "unit"
    CURRENT_JOB = "current_job"
    JOB_IDENTIFIER = "job_identifier"
    JOB_PATH = "job_path"
    JOB_PROPERTIES = "job_properties"
    BEGIN_SEQUENCE = "begin_sequence"
    SEQUENCE = "sequence"
    OBSERVED_NS = "observed_ns"
    UNCLASSIFIED = "unclassified"
    CREATORS = "creators"


@dataclass(frozen=True)
class GraphNode:
    """One actual original-connection unit read and its source classification."""

    read: UnitRead
    source_kind: SourceKind
    sources: tuple[JsonObject, ...]
    current_job: JobRead | None

    def record(self) -> JsonObject:
        """A current job is supporting data, never a substitute for accepted-call settlement."""
        job = self.current_job
        return {
            Key.NAME: self.read.name,
            Key.OBJECT_PATH: self.read.object_path,
            Key.UNIT: {key: self.read.unit.get(key) for key in UNIT_FIELDS},
            Key.SOURCE_KIND: self.source_kind.value,
            Key.SOURCES: list[JsonValue](self.sources),
            Key.CURRENT_JOB: {
                Key.JOB_IDENTIFIER: job.identifier,
                Key.JOB_PATH: job.object_path,
                Key.JOB_PROPERTIES: dict(job.properties),
                Key.BEGIN_SEQUENCE: job.begin_sequence,
                Key.SEQUENCE: job.sequence,
                Key.OBSERVED_NS: job.observed_ns,
            }
            if job is not None
            else None,
            Key.BEGIN_SEQUENCE: self.read.begin_sequence,
            Key.SEQUENCE: self.read.sequence,
            Key.OBSERVED_NS: self.read.observed_ns,
        }


@dataclass(frozen=True)
class DependencyGraph:
    """A finite cut of native dependencies/sources; no continuity seal, creator closure or job-settlement verdict."""

    nodes: tuple[GraphNode, ...]
    begin_sequence: int
    sequence: int
    observed_ns: int
    creators: tuple[str, ...]

    @property
    def unclassified(self) -> tuple[str, ...]:
        """Keep unknown source nodes explicit and blocking for ensuing admission."""
        return tuple(node.read.name for node in self.nodes if node.source_kind is SourceKind.UNCLASSIFIED)

    def record(self) -> JsonObject:
        """Retain complete reached-node facts without declaring that a partial census sealed admission."""
        return {
            Key.NODES: [node.record() for node in self.nodes],
            Key.UNCLASSIFIED: list[JsonValue](self.unclassified),
            Key.CREATORS: list[JsonValue](self.creators),
            Key.BEGIN_SEQUENCE: self.begin_sequence,
            Key.SEQUENCE: self.sequence,
            Key.OBSERVED_NS: self.observed_ns,
        }


def _references(read: UnitRead, keys: tuple[str, ...]) -> frozenset[str]:
    found: set[str] = set()
    for key in keys:
        value = read.unit.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError(ERROR_GRAPH)
        names = {item for item in value if isinstance(item, str)}
        if len(names) != len(value):
            raise ValueError(ERROR_GRAPH)
        found.update(names)
    return frozenset(found)


class GraphSources:
    """The existing static/recipe file checker, shared only within this one finite native census."""

    def __init__(
        self,
        package: StaticPackage,
        configuration: InstanceConfiguration,
        deadline: AdmittedDeadline,
        masked: MaskedInstanceConfiguration | None,
    ) -> None:
        rows = parse_object(package.lock_bytes)[HostKey.ACTIVATION_SOURCES]
        if not isinstance(rows, list):
            raise ValueError(ERROR_GRAPH)
        self._files: dict[Path, JsonObject] = {}
        self._aliases: dict[str, JsonObject] = {}
        self._checked: dict[Path, JsonObject] = {}
        self._owned: dict[Path, JsonObject] = {}
        self.deadline = deadline
        self.masked = masked
        if masked is not None and configuration is not masked.current:
            raise ValueError(ERROR_GRAPH)
        for value in rows:
            row = object_value(value)
            relative = Path(text(row, Field.PATH))
            if row.get(HostKey.SCOPE) != HostKey.HOST or not relative.is_relative_to(UNIT_DIRECTORY):
                continue
            if row.get(HostKey.KIND) == Kind.FILE:
                self._files[ROOT / relative] = row
            elif row.get(HostKey.KIND) == Kind.SYMLINK and relative.parent == UNIT_DIRECTORY:
                self._aliases[relative.name] = row
        for row in configuration.files:
            self._owned[Path(text(row, Field.PATH))] = row

    def classify(self, read: UnitRead) -> tuple[SourceKind, tuple[JsonObject, ...]]:
        """Unknown source/alias/drop-in facts remain unknown; no generated or transient wildcard is approved."""
        unit = read.unit
        if self.masked is not None and read is self.masked.current.guest:
            # Only this positively checked owned mask uses the post-mask predicates; there is no masked-unit wildcard.
            return SourceKind.MASKED, (self.masked.mask, *self.masked.current.files)
        if (
            unit.get(ConfigurationKey.LOAD_STATE) != LOADED
            or unit.get(ConfigurationKey.TRANSIENT) is not False
            or unit.get(ConfigurationKey.NEED_RELOAD) is not False
        ):
            return SourceKind.UNCLASSIFIED, ()
        names = _references(read, (ConfigurationKey.NAMES,))
        drop_ins = _references(read, (ConfigurationKey.DROP_IN_PATHS,))
        fragment = unit.get(ConfigurationKey.FRAGMENT_PATH)
        source = unit.get(ConfigurationKey.SOURCE_PATH)
        canonical = unit.get(ConfigurationKey.ID)
        if not isinstance(canonical, str) or canonical not in names or read.name not in names:
            return SourceKind.UNCLASSIFIED, ()
        if fragment == EMPTY and not drop_ins and names == frozenset({read.name}):
            if (read.name in NATIVE_SLICES and source == EMPTY) or (
                read.name == ROOT_MOUNT and source in (EMPTY, MOUNTINFO)
            ):
                return SourceKind.MANAGER_NATIVE, ()
        if not isinstance(fragment, str) or not fragment or source != EMPTY:
            return SourceKind.UNCLASSIFIED, ()
        if any(name != canonical and name not in self._aliases for name in names):
            return SourceKind.UNCLASSIFIED, ()
        for name in names - {canonical}:
            row = self._aliases[name]
            _locked_file(row, self.deadline)
            if (ROOT / text(row, Field.PATH)).resolve(strict=True) != Path(fragment).resolve(strict=True):
                return SourceKind.UNCLASSIFIED, ()
        expected_file = canonical
        if INSTANCE_SEPARATOR in canonical:
            prefix, _ = canonical.split(INSTANCE_SEPARATOR, 1)
            expected_template = prefix + INSTANCE_SEPARATOR + Path(canonical).suffix
            if Path(fragment).name == expected_template:
                expected_file = expected_template
        if Path(fragment).name != expected_file:
            return SourceKind.UNCLASSIFIED, ()
        sources: list[JsonObject] = []
        kind = SourceKind.LOCKED
        for address in (fragment, *sorted(drop_ins)):
            path = Path(address)
            if path in self._owned:
                row = self._owned[path]
                kind = SourceKind.RECIPE
            elif path in self._files:
                row = self._files[path]
            else:
                return SourceKind.UNCLASSIFIED, tuple(sources)
            if path not in self._checked:
                check: JsonObject = {
                    **row,
                    Field.PATH: str(path.relative_to(ROOT)),
                    HostKey.KIND: Kind.FILE.value,
                }
                _locked_file(check, self.deadline)
                self._checked[path] = {
                    Field.PATH: str(path),
                    Field.SHA256: row[Field.SHA256],
                    Field.BYTES: row[Field.BYTES],
                }
            sources.append(self._checked[path])
        return kind, tuple(sources)


async def inspect_dependency_graph(
    manager: ManagerObserver,
    package: StaticPackage,
    configuration: InstanceConfiguration,
    deadline: AdmittedDeadline,
    accepted: tuple[AcceptedJob, ...],
    *,
    masked: MaskedInstanceConfiguration | None = None,
    previous: DependencyGraph | None = None,
) -> DependencyGraph:
    """Read each reached object once on the original connection; neither resubscribe nor repeat a manager scan."""
    end_ns = deadline.effective_end()
    begin = manager.sequence
    if (masked is None) != (previous is None):
        raise ValueError(ERROR_GRAPH)
    sources = GraphSources(package, configuration, deadline, masked)
    roots = {configuration.parent.name, configuration.guest.name}
    reads: dict[str, UnitRead] = {
        configuration.parent.name: configuration.parent,
        configuration.guest.name: configuration.guest,
    }
    prior = {node.read.name: node for node in previous.nodes} if previous is not None else {}
    if previous is not None:
        manager.reconcile_jobs(
            frozenset(previous.creators) | frozenset(roots) | frozenset(job.unit_name for job in accepted), accepted
        )
    for job in accepted:
        if job.unit_name not in roots and previous is not None:
            # Its earlier source/lifecycle evidence stays in the prior graph. A finished auxiliary may already be GC'd.
            node = prior.get(job.unit_name)
            if node is None or node.read.object_path != job.unit_path:
                raise ValueError(ERROR_GRAPH)
            continue
        if job.unit_name not in reads:
            reads[job.unit_name] = await manager.read_unit(job.unit_name, None, end_ns)
        if reads[job.unit_name].object_path != job.unit_path:
            manager.invalidate(Invalidation.UNKNOWN_ACTIVATOR)
            raise ValueError(ERROR_GRAPH)
    expand: list[str] = sorted(reads)
    expanded: set[str] = set()
    while expand:
        if time.monotonic_ns() >= end_ns:
            raise TimeoutError(ERROR_GRAPH)
        name = expand.pop()
        if name in expanded:
            continue
        expanded.add(name)
        read = reads[name]
        # Record ordering endpoints, while recursively following only work-creation/propagation edges.
        for target in sorted(_references(read, UNIT_REFERENCE_PROPERTIES)):
            if target not in reads:
                reads[target] = await manager.read_referenced_unit(read, target, end_ns)
        recurse = _references(read, CREATION_EDGES)
        if name in roots:
            recurse |= _references(read, ROOT_ACTIVATORS)
        expand.extend(sorted(recurse - expanded))
    nodes: list[GraphNode] = []
    for _name, read in sorted(reads.items()):
        if time.monotonic_ns() >= end_ns:
            raise TimeoutError(ERROR_GRAPH)
        kind, files = sources.classify(read)
        nodes.append(GraphNode(read, kind, files, await manager.read_unit_job(read, end_ns)))
    if manager.faults or time.monotonic_ns() >= end_ns:
        raise ValueError(ERROR_GRAPH)
    return DependencyGraph(tuple(nodes), begin, manager.sequence, time.monotonic_ns(), tuple(sorted(expanded)))

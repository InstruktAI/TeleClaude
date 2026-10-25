"""Typed references: the one routing vocabulary for the things an event names.

A reference states a kind of thing and that thing's identity. The kinds are a
closed set owned here; a reader tolerates a kind it does not know by keeping
kind and identity as opaque strings (`EventRef`), so a kind added on a newer
computer never fails an older reader. Producers build references through the
per-kind classes, whose kind is fixed by the class.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

_TOKEN_SEPARATOR = ":"
_EMPTY_IDENTITY_ERROR = "a reference identity must be non-empty"
_MALFORMED_TOKEN_ERROR = "a reference token is '<kind>:<identity>'"


class ReferenceKind(StrEnum):
    """Closed set of kinds of thing a reference can name."""

    TODO = "todo"
    SESSION = "session"
    OPERATION = "operation"
    JOB = "job"
    EVENT_TYPE = "event_type"
    COMPUTER = "computer"
    CONFIGURATION = "configuration"
    STREAM_ENTRY = "stream_entry"
    CAPTURED_ITEM = "captured_item"
    INBOUND_SOURCE = "inbound_source"
    SIGNAL_ITEM = "signal_item"
    SIGNAL_CLUSTER = "signal_cluster"
    SIGNAL_SYNTHESIS = "signal_synthesis"
    DEPLOYMENT = "deployment"
    SCHEMA_PROPOSAL = "schema_proposal"
    ESCALATION = "escalation"
    MEMORY_SCOPE = "memory_scope"
    CI_RUN = "ci_run"
    COMMIT = "commit"
    INSTALL = "install"


@dataclass(frozen=True)
class EventRef:
    """A reference as it travels and as a reader sees it: kind and identity, both opaque."""

    kind: str
    identity: str

    def __post_init__(self) -> None:
        if not self.kind or not self.identity:
            raise ValueError(_MALFORMED_TOKEN_ERROR)

    def to_token(self) -> str:
        return f"{self.kind}{_TOKEN_SEPARATOR}{self.identity}"

    @classmethod
    def from_token(cls, token: str) -> EventRef:
        kind, separator, identity = token.partition(_TOKEN_SEPARATOR)
        if not separator:
            raise ValueError(_MALFORMED_TOKEN_ERROR)
        return cls(kind=kind, identity=identity)

    def is_kind(self, kind: ReferenceKind) -> bool:
        return self.kind == kind.value

    def to_ref(self) -> EventRef:
        return self


@dataclass(frozen=True)
class TypedRef:
    """A reference whose kind is fixed by the subclass; producers construct these."""

    KIND: ClassVar[ReferenceKind]
    identity: str

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError(_EMPTY_IDENTITY_ERROR)

    def to_ref(self) -> EventRef:
        return EventRef(kind=self.KIND.value, identity=self.identity)


#: Any reference a producer can state: a typed one, or a received one carried on unchanged.
Reference = TypedRef | EventRef


@dataclass(frozen=True)
class TodoRef(TypedRef):
    """A todo, by slug; the event's home names its project."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.TODO


@dataclass(frozen=True)
class SessionRef(TypedRef):
    """An agent session, by session id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.SESSION


@dataclass(frozen=True)
class OperationRef(TypedRef):
    """A durable operation, by its persisted operation id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.OPERATION


@dataclass(frozen=True)
class JobRef(TypedRef):
    """A recurring job, by its project-qualified job key (the name alone for a legacy key)."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.JOB


@dataclass(frozen=True)
class EventTypeRef(TypedRef):
    """An event type, by its type name."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.EVENT_TYPE


@dataclass(frozen=True)
class ComputerRef(TypedRef):
    """A computer, by computer name."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.COMPUTER


@dataclass(frozen=True)
class ConfigurationRef(TypedRef):
    """A configuration: the machine, the global configuration, or a project slug."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.CONFIGURATION


@dataclass(frozen=True)
class StreamEntryRef(TypedRef):
    """A stream entry, by stream name and entry id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.STREAM_ENTRY


@dataclass(frozen=True)
class CapturedItemRef(TypedRef):
    """A captured item, by its inbox entry path or content id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.CAPTURED_ITEM


@dataclass(frozen=True)
class InboundSourceRef(TypedRef):
    """A declared inbound source, by protocol and declaring home (or global)."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.INBOUND_SOURCE


@dataclass(frozen=True)
class SignalItemRef(TypedRef):
    """A signal item, by item id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.SIGNAL_ITEM


@dataclass(frozen=True)
class SignalClusterRef(TypedRef):
    """A signal cluster, by cluster id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.SIGNAL_CLUSTER


@dataclass(frozen=True)
class SignalSynthesisRef(TypedRef):
    """A signal synthesis, by the id of the cluster it synthesises."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.SIGNAL_SYNTHESIS


@dataclass(frozen=True)
class DeploymentRef(TypedRef):
    """A deployment: the deployed project, one thing across all its deployments."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.DEPLOYMENT


@dataclass(frozen=True)
class SchemaProposalRef(TypedRef):
    """A schema proposal, by proposal id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.SCHEMA_PROPOSAL


@dataclass(frozen=True)
class EscalationRef(TypedRef):
    """An escalation, by escalation id."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.ESCALATION


@dataclass(frozen=True)
class MemoryScopeRef(TypedRef):
    """A memory scope, by identity key, with ``@<desk>`` appended for the memories kept at one help desk."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.MEMORY_SCOPE


@dataclass(frozen=True)
class CiRunRef(TypedRef):
    """A CI run attempt, by ``<repository_id>/<run_id>/<attempt>``; a re-run is a new attempt."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.CI_RUN


@dataclass(frozen=True)
class CommitRef(TypedRef):
    """A commit of a repository, by ``<repository_id>/<sha>``."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.COMMIT


@dataclass(frozen=True)
class InstallRef(TypedRef):
    """An install of a release on a computer, by ``<computer>/<number>``; the number is the installation's own."""

    KIND: ClassVar[ReferenceKind] = ReferenceKind.INSTALL

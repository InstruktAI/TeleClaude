"""The kind-addressed engine's shared contract: types, refusals, and primitives.

Owned here so `teleclaude.config.resources`'s per-kind implementations and this
module's own typed vocabulary never depend on each other in a cycle: every
kind's read/init/patch logic imports its addressing types, typed refusals, the
`config_resource_change` observation helper, and the multi-file commit-with-
rollback primitive from here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config._file_io import FileTransaction
from teleclaude.config.migrations._chain import Destination
from teleclaude.config.migrations._runner import carry_pending
from teleclaude.config.revision import StaleRevision
from teleclaude.config.roster import RosterRefused
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef

_CONFIG_RESOURCE_CHANGE_EVENT = "config_resource_change"
_PERSON_KEY_DERIVED_FIELD = "person_key_derived"
_DERIVED_KEY_MATCHES_FIELD = "derived_key_matches_instance"

logger = get_logger(__name__)


@dataclass(frozen=True)
class SubjectView:
    """The addressed, writable-plus-read-only view of one configuration subject."""

    ref: SubjectRef
    sources: tuple[Path, ...]
    sections: Mapping[str, object]  # guard: loose-dict - heterogeneous per-kind config sections
    read_only: Mapping[str, object]  # guard: loose-dict - heterogeneous per-kind projected sections
    revision: str


class SubjectNotFound(ValueError):
    """The addressed subject has no backing document yet."""


class InvalidCandidate(ValueError):
    """A patch candidate failed schema or cross-reference validation."""


class ReadOnlyProjection(ValueError):
    """A patch named a section this subject does not accept writes to."""


class ResourceChangeOutcome(StrEnum):
    """Closed outcome vocabulary for the `config_resource_change` terminal record.

    A failure outcome is decided only from evidence the operation itself
    holds about its own writes — never from the exception type, and never
    from re-reading a target after its lock was released, because another
    writer may have changed it since. `ROLLED_BACK` means the operation's own
    evidence shows none of its writes remain (it failed before any write took
    effect, or its own compensation restored every replacement while still
    holding the locks). `PARTIALLY_COMMITTED` means its own evidence shows at
    least one of its writes remains (a compensation that failed, or a step it
    completed before a later step failed); `unrestored_targets` names each.
    `UNCONFIRMED` means the failure occurred inside a write the engine does
    not observe step by step (a scaffold, a directory deletion, project init,
    a token issue, an environment write) and no own-evidence establishes
    either of the others. Forbidden: `ROLLED_BACK` while the operation's own
    evidence shows a write of its own remains, and `PARTIALLY_COMMITTED`
    naming no target.
    """

    COMMITTED = "committed"
    UNCHANGED = "unchanged"
    REFUSED_STALE = "refused_stale"
    REFUSED_INVALID = "refused_invalid"
    REFUSED_PROJECTION = "refused_projection"
    NOT_FOUND = "not_found"
    ROLLED_BACK = "rolled_back"
    PARTIALLY_COMMITTED = "partially_committed"
    UNCONFIRMED = "unconfirmed"


class ResourceOperation(StrEnum):
    """Closed operation vocabulary for the `config_resource_change` terminal record."""

    INIT = "init"
    PATCH = "patch"
    REMOVE = "remove"


class TargetDocument(StrEnum):
    """Closed document vocabulary for an `unrestored_targets` semantic identifier.

    An identifier is `<kind>[:<instance>]:<document>` (for example
    `person:ada:overlay`, `global:registry`) — never a filesystem path.
    """

    MACHINE = "machine"
    REGISTRY = "registry"
    OVERLAY = "overlay"
    ROSTER = "roster"
    INVITATIONS = "invitations"
    HANDOFF = "handoff"
    ENVIRONMENT = "environment"
    WORKSPACE = "workspace"
    PLUMBING = "plumbing"


_DESTINATION_DOCUMENTS: Final[dict[Destination, TargetDocument]] = {
    Destination.INVITATIONS: TargetDocument.INVITATIONS,
    Destination.HANDOFF: TargetDocument.HANDOFF,
}


def target_document_for_destination(destination: Destination) -> TargetDocument:
    """Resolve the resource evidence identifier for one migration destination."""
    return _DESTINATION_DOCUMENTS[destination]


def target_id(kind: ConfigSubjectKind, instance: str | None, document: TargetDocument) -> str:
    """Build one `unrestored_targets` semantic identifier."""
    return f"{kind.value}:{instance}:{document.value}" if instance else f"{kind.value}:{document.value}"


def delivery_recorder(ref: SubjectRef, evidence: OwnEvidence) -> Callable[[Destination], None]:
    """Mark each migration destination as an operation-owned write when it lands."""

    def record(destination: Destination) -> None:
        evidence.mark(target_id(ref.kind, ref.instance, target_document_for_destination(destination)))

    return record


def carry_resource_migrations(stored: Mapping[str, object], ref: SubjectRef, evidence: OwnEvidence) -> None:
    """Deliver pending values and attach their successful writes to the resource outcome."""
    carry_pending(stored, ref, delivered=delivery_recorder(ref, evidence))


def emit_resource_change(
    *,
    request_id: str | None,
    kind: ConfigSubjectKind,
    instance: str | None,
    operation: ResourceOperation,
    outcome: ResourceChangeOutcome,
    revision_before: str | None,
    revision_after: str | None,
    sections: frozenset[str] | None = None,
    companies_written: tuple[str, ...] | None = None,
    removed_assignments: tuple[tuple[str, str], ...] | None = None,
    unrestored_targets: tuple[str, ...] | None = None,
    person_key_derived: bool | None = None,
    derived_key_matches_instance: bool | None = None,
) -> None:
    """Emit the one terminal record every mutating resource verb promises."""
    logger.info(
        _CONFIG_RESOURCE_CHANGE_EVENT,
        request_id=request_id,
        kind=kind.value,
        instance=None if kind is ConfigSubjectKind.PERSON and operation is ResourceOperation.INIT else instance,
        operation=operation.value,
        outcome=outcome.value,
        revision_before=revision_before,
        revision_after=revision_after,
        sections=sorted(sections) if sections else None,
        companies_written=list(companies_written) if companies_written is not None else None,
        removed_assignments=[list(pair) for pair in removed_assignments] if removed_assignments is not None else None,
        unrestored_targets=list(unrestored_targets) if unrestored_targets else None,
        **({_PERSON_KEY_DERIVED_FIELD: person_key_derived} if person_key_derived else {}),
        **(
            {_DERIVED_KEY_MATCHES_FIELD: derived_key_matches_instance}
            if derived_key_matches_instance is not None
            else {}
        ),
    )


def outcome_for_refusal(exc: Exception) -> ResourceChangeOutcome:
    """Map one typed candidate-validation refusal to its observation outcome token."""
    if isinstance(exc, StaleRevision):
        return ResourceChangeOutcome.REFUSED_STALE
    if isinstance(exc, ReadOnlyProjection):
        return ResourceChangeOutcome.REFUSED_PROJECTION
    if isinstance(exc, SubjectNotFound):
        return ResourceChangeOutcome.NOT_FOUND
    # InvalidCandidate, RosterRefused
    return ResourceChangeOutcome.REFUSED_INVALID


REFUSAL_TYPES = (StaleRevision, InvalidCandidate, ReadOnlyProjection, SubjectNotFound, RosterRefused)


@dataclass(frozen=True)
class CommitEntry:
    """One held file transaction paired with its committed and candidate text."""

    transaction: FileTransaction
    committed_text: str
    candidate_text: str


class PartialCommitFailure(RuntimeError):
    """A multi-file commit failed and at least one rollback also failed.

    The named paths may still hold their (uncommitted) candidate text rather
    than their prior committed text — a caller must never treat this the same
    as a clean refusal that left every file untouched.
    """

    def __init__(self, failed_paths: tuple[Path, ...], original: BaseException) -> None:
        self.failed_paths = failed_paths
        self.original = original
        joined = ", ".join(str(path) for path in failed_paths)
        super().__init__(f"Rollback failed for {joined} after {original!r}; these paths may hold uncommitted content.")


def commit_documents(entries: Sequence[CommitEntry]) -> None:
    """Replace every entry's file, restoring already-replaced files on failure.

    Every candidate is assumed already rendered and validated by the caller;
    this function performs no validation, only ordered replacement with
    rollback. Callers hold every entry's transaction lock for the duration.
    A rollback failure is never swallowed: it is raised as `PartialCommitFailure`
    naming every path that could not be restored, chained to the original error,
    only after every remaining rollback has still been attempted.
    """
    replaced: list[CommitEntry] = []
    try:
        for entry in entries:
            entry.transaction.replace_text(entry.candidate_text)
            replaced.append(entry)
    except BaseException as original:
        failed_paths: list[Path] = []
        for entry in reversed(replaced):
            try:
                entry.transaction.replace_text(entry.committed_text)
            except OSError:
                failed_paths.append(entry.transaction.path)
        if failed_paths:
            raise PartialCommitFailure(tuple(failed_paths), original) from original
        raise


def apply_merge_patch(
    base: Mapping[str, object],  # guard: loose-dict - RFC 7386 patch source is caller-shaped
    patch: Mapping[str, object],  # guard: loose-dict - RFC 7386 patch source is caller-shaped
) -> dict[str, object]:  # guard: loose-dict - RFC 7386 patch result is caller-shaped
    """Apply an RFC 7386 JSON Merge Patch: mapping keys merge, `None` removes, else replace."""
    result: dict[str, object] = deepcopy(dict(base))  # guard: loose-dict - RFC 7386 patch result is caller-shaped
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
            continue
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = apply_merge_patch(current, value)
        else:
            result[key] = deepcopy(value)
    return result


class OwnEvidence:
    """One operation's own evidence of what it has written, held while it holds its locks.

    `mark` records a target as a completed, remaining write the moment a step
    succeeds (a single-file replace, a `commit_documents` call). `enter_unobserved`
    flags that the next call is a flow the engine does not observe step by
    step (a scaffold, a directory deletion, project init, a token issue, an
    environment write). `run_observed`'s failure branch reads both: any
    remaining target means `partially_committed`; otherwise a failure inside
    an unobserved flow means `unconfirmed`; otherwise `rolled_back`.
    """

    def __init__(self) -> None:
        self._remaining: list[str] = []
        self._unobserved = False

    def mark(self, *targets: str) -> None:
        self._remaining.extend(targets)

    def enter_unobserved(self) -> None:
        self._unobserved = True

    @property
    def remaining(self) -> tuple[str, ...]:
        return tuple(self._remaining)

    @property
    def unobserved(self) -> bool:
        return self._unobserved


def run_observed[T](
    compute: Callable[[OwnEvidence], T],
    *,
    request_id: str | None,
    kind: ConfigSubjectKind,
    instance: str | None,
    operation: ResourceOperation,
    revision_before: str | None,
    sections: frozenset[str] | None = None,
    person_key_derived: bool | None = None,
) -> T:
    """Run one mutation, emitting the shared record for every way it can fail.

    Success is left to the caller to observe: the outcome (`committed` vs
    `unchanged`) and `revision_after` depend on the verb's own return shape,
    which this generic wrapper doesn't know. Every failure shape reduces to
    one decision, made once here from `evidence` (threaded to `compute`):
    a typed candidate refusal, or anything else — for which `evidence.remaining`
    settles `partially_committed`, `evidence.unobserved` settles `unconfirmed`,
    and their absence settles `rolled_back`.
    """
    evidence = OwnEvidence()
    try:
        return compute(evidence)
    except REFUSAL_TYPES as exc:
        emit_resource_change(
            request_id=request_id,
            kind=kind,
            instance=instance,
            operation=operation,
            outcome=outcome_for_refusal(exc),
            revision_before=revision_before,
            revision_after=None,
            sections=sections,
            person_key_derived=person_key_derived,
        )
        raise
    except BaseException:
        if evidence.remaining:
            outcome = ResourceChangeOutcome.PARTIALLY_COMMITTED
        elif evidence.unobserved:
            outcome = ResourceChangeOutcome.UNCONFIRMED
        else:
            outcome = ResourceChangeOutcome.ROLLED_BACK
        emit_resource_change(
            request_id=request_id,
            kind=kind,
            instance=instance,
            operation=operation,
            outcome=outcome,
            revision_before=revision_before,
            revision_after=None,
            sections=sections,
            unrestored_targets=evidence.remaining or None,
            person_key_derived=person_key_derived,
        )
        raise

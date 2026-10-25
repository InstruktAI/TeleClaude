"""The convergence decision record: the release held for the installation inspector and the last decision with its reason.

Per installation, beside the pending convergence record and outside the platform home's retained set
(``local/projects/teleclaude/spec/domain/reconciliation``, Channel convergence). It holds the facts
``telec app status`` renders, which are not admissions: the newest admitted edge revision is the newest pending
edge entry of the pending store and is not copied here. A hold lasts while its release is later than the active
release, so installing the release or any later one ends it however the install happened.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from teleclaude.deployment import parse_version
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import MIGRATION_STATE_PATH

CONVERGENCE_DECISION_PATH = MIGRATION_STATE_PATH.parent / "convergence_decision.json"

_DECISION_SCHEMA_VERSION: Literal[1] = 1
_TEXT_ENCODING = "utf-8"


class DecisionOutcome(StrEnum):
    """What the installation's channel decided at its last signal or interval read."""

    ADMITTED = "admitted"
    HELD = "held"
    NOTHING_NEWER = "nothing_newer"
    SKIPPED = "skipped"
    UNDETERMINED = "undetermined"


class HeldRelease(BaseModel):
    """A published release beyond the active release's compatibility series, held for the installation inspector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    tag: str
    version: str
    held_at: datetime
    announced: bool = False


class LastDecision(BaseModel):
    """The most recent convergence decision: what was decided, the sentence that says why, and when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: DecisionOutcome
    reason: str
    at: datetime


class ConvergenceRecord(BaseModel):
    """What the installation knows about its channel's convergence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _DECISION_SCHEMA_VERSION
    held: HeldRelease | None = None
    last: LastDecision | None = None

    def holding(self, active: tuple[int, int, int] | None) -> HeldRelease | None:
        """The release still held over the active release; none once the active release reaches it."""
        if self.held is None:
            return None
        if active is not None and parse_version(self.held.version) <= active:
            return None
        return self.held

    def decided(
        self,
        outcome: DecisionOutcome,
        reason: str,
        held: HeldRelease | None,
        active: tuple[int, int, int] | None,
        at: datetime,
    ) -> ConvergenceRecord:
        """This record once a decision is made.

        A candidate hold replaces the current one only when it is a later release: while the active release is
        unchanged, an older or reordered signal never displaces the newest outstanding release. An installed
        release ends the hold.
        """
        current = self.holding(active)
        replaces = held is not None and (current is None or _is_later(held, current))
        return ConvergenceRecord(
            held=held if replaces else current, last=LastDecision(outcome=outcome, reason=reason, at=at)
        )

    def announced(self, held: HeldRelease) -> ConvergenceRecord:
        """This record once the hold ``held`` names has been announced; a different hold stays as it is."""
        if self.held is None or (self.held.source, self.held.version) != (held.source, held.version):
            return self
        return ConvergenceRecord(held=self.held.model_copy(update={"announced": True}), last=self.last)


def _is_later(candidate: HeldRelease, current: HeldRelease) -> bool:
    """Whether the candidate is a different source's release or a later version of the same source's."""
    return candidate.source != current.source or parse_version(candidate.version) > parse_version(current.version)


def read_convergence(path: Path = CONVERGENCE_DECISION_PATH) -> ConvergenceRecord:
    """The convergence record, or an empty one before the first decision."""
    return (
        ConvergenceRecord.model_validate_json(path.read_text(encoding=_TEXT_ENCODING))
        if path.is_file()
        else ConvergenceRecord()
    )


def update_convergence(
    transform: Callable[[ConvergenceRecord], ConvergenceRecord], path: Path = CONVERGENCE_DECISION_PATH
) -> ConvergenceRecord:
    """Replace the record with ``transform`` of its current value, atomically under one lock; return the result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_transaction(path) as transaction:
        text = transaction.read_text(encoding=_TEXT_ENCODING)
        current = ConvergenceRecord.model_validate_json(text) if text.strip() else ConvergenceRecord()
        updated = transform(current)
        transaction.replace_text(updated.model_dump_json(), encoding=_TEXT_ENCODING)
    return updated


def record_decision(
    outcome: DecisionOutcome, reason: str, held: HeldRelease | None, active: tuple[int, int, int] | None
) -> ConvergenceRecord:
    """Record one decision with its reason, and the release it newly holds, when it holds one."""
    at = datetime.now(UTC)
    return update_convergence(lambda record: record.decided(outcome, reason, held, active, at))


def mark_hold_announced(held: HeldRelease) -> ConvergenceRecord:
    """Record that the held-release event for ``held`` was emitted."""
    return update_convergence(lambda record: record.announced(held))

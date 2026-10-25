"""The check-failures record: a failed-check bug's failures, occurrences and recoveries, as the filer keeps them.

The record is one artifact of the bug. Its header names the fingerprint and the failure it identifies; its entries are
appended, never changed, and each is keyed so that handling the same completion again appends nothing. Only the
platform's failed-check filer writes it. A reader sees a short markdown document; the filer reads the same document
back through the entry models below.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

_FINGERPRINT_LENGTH: Final = 16
_FINGERPRINT_PART_SEPARATOR: Final = "\x1f"
_NEWLINE: Final = "\n"
_EMPTY_LINE: Final = ""
_TITLE: Final = "# Check failures"
_FINGERPRINT_LABEL: Final = "Fingerprint: "
_WORKFLOW_LABEL: Final = "Workflow: "
_JOB_LABEL: Final = "Job: "
_STEP_LABEL: Final = "Step: "
_ENTRIES_HEADING: Final = "## Entries"
_ENTRY_PREFIX: Final = "- "
_PREAMBLE: Final = (
    "The platform's failed-check filer appends to this record; earlier entries never change.\n"
    "Each entry is one line of JSON."
)
_MALFORMED_ERROR: Final = "check-failures record has no {label}line"


class EntryKind(StrEnum):
    """The kinds of entry a record holds."""

    FAILURE = "failure"
    RECOVERY = "recovery"
    ANNOUNCED = "announced"


class CommitEntry(BaseModel):
    """A commit of the range a failure covers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha: str
    subject: str


class FailureEntry(BaseModel):
    """One occurrence of the failure: a run attempt's failed job, and where it failed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[EntryKind.FAILURE] = EntryKind.FAILURE
    run_id: int
    run_url: str
    attempt: int
    job: str
    branch: str
    revision: str
    last_green_revision: str | None
    commits: list[CommitEntry]


class RecoveryEntry(BaseModel):
    """A green run of the check on a branch where the record holds a failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[EntryKind.RECOVERY] = EntryKind.RECOVERY
    run_id: int
    run_url: str
    attempt: int
    branch: str
    revision: str


class AnnouncedEntry(BaseModel):
    """The bug's creation has been announced to the lifecycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[EntryKind.ANNOUNCED] = EntryKind.ANNOUNCED


type Entry = Annotated[FailureEntry | RecoveryEntry | AnnouncedEntry, Field(discriminator="kind")]
_ENTRY: Final[TypeAdapter[Entry]] = TypeAdapter(Entry)


def fingerprint_of(workflow_path: str, job: str, step: str) -> str:
    """The identity of a failure: the check, the job and the step, shortened."""
    parts = _FINGERPRINT_PART_SEPARATOR.join((workflow_path, job, step))
    return sha256(parts.encode()).hexdigest()[:_FINGERPRINT_LENGTH]


def fingerprint_line(fingerprint: str) -> str:
    """The line that states a fingerprint, in the record and in the bug's input alike."""
    return _FINGERPRINT_LABEL + fingerprint


@dataclass(frozen=True)
class CheckFailures:
    """A parsed record: the failure it identifies and its entries in the order they were appended."""

    fingerprint: str
    workflow_path: str
    job: str
    step: str
    entries: tuple[FailureEntry | RecoveryEntry | AnnouncedEntry, ...] = ()

    @classmethod
    def start(cls, workflow_path: str, job: str, step: str) -> CheckFailures:
        """An empty record for one failure."""
        return cls(
            fingerprint=fingerprint_of(workflow_path, job, step), workflow_path=workflow_path, job=job, step=step
        )

    @classmethod
    def parse(cls, text: str) -> CheckFailures:
        """Read a record back; its header must be present, and every entry line must be well formed."""
        lines = text.split(_NEWLINE)
        fingerprint = _labelled(lines, _FINGERPRINT_LABEL)
        workflow_path = _labelled(lines, _WORKFLOW_LABEL)
        job = _labelled(lines, _JOB_LABEL)
        step = _labelled(lines, _STEP_LABEL)
        after_heading = lines[lines.index(_ENTRIES_HEADING) + 1 :] if _ENTRIES_HEADING in lines else []
        entries = tuple(
            _ENTRY.validate_json(line.removeprefix(_ENTRY_PREFIX))
            for line in after_heading
            if line.startswith(_ENTRY_PREFIX)
        )
        return cls(fingerprint=fingerprint, workflow_path=workflow_path, job=job, step=step, entries=entries)

    def render(self) -> str:
        """The record as the document the artifact holds."""
        header = (
            _TITLE,
            _EMPTY_LINE,
            _PREAMBLE,
            _EMPTY_LINE,
            fingerprint_line(self.fingerprint),
            _WORKFLOW_LABEL + self.workflow_path,
            _JOB_LABEL + self.job,
            _STEP_LABEL + self.step,
            _EMPTY_LINE,
            _ENTRIES_HEADING,
        )
        entries = tuple(_ENTRY_PREFIX + _ENTRY.dump_json(entry).decode() for entry in self.entries)
        return _NEWLINE.join((*header, *entries)) + _NEWLINE

    def append(self, entry: FailureEntry | RecoveryEntry | AnnouncedEntry) -> CheckFailures:
        """The record with one more entry after the existing ones."""
        return CheckFailures(
            fingerprint=self.fingerprint,
            workflow_path=self.workflow_path,
            job=self.job,
            step=self.step,
            entries=(*self.entries, entry),
        )

    def holds_failure(self, run_id: int, attempt: int, job: str) -> bool:
        """Whether this run attempt's failed job is already recorded."""
        return any(
            isinstance(entry, FailureEntry) and (entry.run_id, entry.attempt, entry.job) == (run_id, attempt, job)
            for entry in self.entries
        )

    def recovery_due(self, branch: str, run_id: int, attempt: int) -> bool:
        """Whether a green run is the recovery of the branch's latest recorded failure.

        Runs are ordered by run id, then attempt. A green run no later than the latest failure on the branch
        recovers nothing, and a failure already followed by a later recovery needs no second one.
        """
        failures = [
            (entry.run_id, entry.attempt)
            for entry in self.entries
            if isinstance(entry, FailureEntry) and entry.branch == branch
        ]
        if not failures:
            return False
        latest_failure = max(failures)
        if (run_id, attempt) <= latest_failure:
            return False
        return not any(
            isinstance(entry, RecoveryEntry)
            and entry.branch == branch
            and (entry.run_id, entry.attempt) > latest_failure
            for entry in self.entries
        )

    @property
    def announced(self) -> bool:
        """Whether the bug's creation has been announced."""
        return any(isinstance(entry, AnnouncedEntry) for entry in self.entries)


def _labelled(lines: list[str], label: str) -> str:
    """The value of the first header line with this label."""
    for line in lines:
        if line.startswith(label):
            return line.removeprefix(label)
    raise ValueError(_MALFORMED_ERROR.format(label=label))

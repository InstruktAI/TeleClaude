"""The assessment record: which installs still owe the installation inspector's assessment, and the last one recorded.

Every install that opens its stopped window owes one assessment of the release that runs after it
(``local/projects/teleclaude/spec/feature/reconciliation/installed-releases``, Assessment after an install),
made by the installation inspector.
The record lives beside the install record, never inside it: the install record validates strictly, so a
release from before this record, rolled back to, would fail to read one that carried new fields. Each owed
install has its own number, and owing one supersedes every earlier owed install: a release that no longer runs
owes no assessment. The record states that installs were assessed, never what the assessment concluded.

Writers go through ``update_assessment`` so the release being installed and ``telec app assessed``
serialize on one lock. The daemon announces what is owed through ``AssessmentAnnouncer``: at its start and at
a fixed interval for as long as an install stays owed, so an announcement that found no recipient is repeated.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict, ValidationError

from teleclaude.core.integration.daemon_window import read_typed_health
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.shutdown_drain import DrainPhase, get_shutdown_drain
from teleclaude.events import EventLevel, EventProducer, EventVisibility
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.references import InstallRef
from teleclaude.events.schemas.installation import InstallationAssessmentOwed, InstallationAssessmentOwedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.file_transaction import file_transaction

logger = get_logger(__name__)

_ASSESSMENT_SCHEMA_VERSION: Literal[1] = 1
_FIRST_NUMBER = 1
_TEXT_ENCODING = "utf-8"
_NOTHING_OWED = "no owed install carries number {number}"
_NOT_SERVING_NO_ACTIVE = "no release is active"
_NOT_SERVING_UNREACHABLE = "the daemon's health could not be read ({error_kind})"
_NOT_SERVING_OTHER_RELEASE = "the daemon serves {serving}, not the active release {active}"
_NOT_SERVING_UNKNOWN_START = "an unknown release"
_NOT_SERVING_NOT_ADMITTING = "the daemon serves the active release {active} but is not admitting work"
_ANNOUNCE_INTERVAL_SECONDS = 900.0
_SUBJECT_IDENTITY = "{computer}/{number}"
_ANNOUNCEMENT_DESCRIPTION = "Install {number} on {computer} owes the assessment of the release that runs after it"
_ANNOUNCEMENT_PRODUCER = "daemon"
_ANNOUNCEMENT_DOMAIN = "installation"
_READ_FAILED_EVENT = "installation_assessment_read_failed"
_ANNOUNCE_FAILED_EVENT = "installation_assessment_announce_failed"
_ANNOUNCED_EVENT = "installation_assessment_announced"


class OwedInstall(BaseModel):
    """An install whose assessment is owed: its number, the revision it installed and when it became owed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int
    revision: str
    owed_since: datetime


class RecordedAssessment(BaseModel):
    """The most recent recorded assessment: the install it covered through and when it was recorded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int
    revision: str
    at: datetime


class NothingOwed(Exception):
    """No owed install carries the number named; ``owed`` holds the installs that are owed."""

    def __init__(self, number: int, owed: tuple[OwedInstall, ...]) -> None:
        super().__init__(_NOTHING_OWED.format(number=number))
        self.number = number
        self.owed = owed


class AssessmentRecord(BaseModel):
    """What the installation knows about the assessments it owes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _ASSESSMENT_SCHEMA_VERSION
    next_number: int = _FIRST_NUMBER
    owed: tuple[OwedInstall, ...] = ()
    last: RecordedAssessment | None = None

    @property
    def newest_owed(self) -> OwedInstall | None:
        """The install most recently owed, or ``None`` when nothing is owed."""
        return self.owed[-1] if self.owed else None

    def owe(self, revision: str, at: datetime) -> AssessmentRecord:
        """This record once an install of ``revision`` owes an assessment, under the next number.

        Each call takes a new number, so a retry of the same revision is a separate obligation, and it
        supersedes every earlier owed install: only the release that runs after it is left to assess.
        """
        install = OwedInstall(number=self.next_number, revision=revision, owed_since=at)
        return AssessmentRecord(next_number=self.next_number + 1, owed=(install,), last=self.last)

    def assessed(self, number: int, at: datetime) -> AssessmentRecord:
        """This record once install ``number`` and every earlier owed install are assessed; later ones stay owed.

        Raises ``NothingOwed`` when no owed install carries ``number``.
        """
        covered = next((install for install in self.owed if install.number == number), None)
        if covered is None:
            raise NothingOwed(number, self.owed)
        remaining = tuple(install for install in self.owed if install.number > number)
        return AssessmentRecord(
            next_number=self.next_number,
            owed=remaining,
            last=RecordedAssessment(number=number, revision=covered.revision, at=at),
        )


def read_assessment(layout: InstallationLayout | None = None) -> AssessmentRecord:
    """The assessment record, or an empty one when the installation has none yet."""
    path = (layout or InstallationLayout()).assessment_record_path
    return (
        AssessmentRecord.model_validate_json(path.read_text(encoding=_TEXT_ENCODING))
        if path.is_file()
        else AssessmentRecord()
    )


def update_assessment(
    transform: Callable[[AssessmentRecord], AssessmentRecord], layout: InstallationLayout | None = None
) -> AssessmentRecord:
    """Replace the record with ``transform`` of its current value, atomically under one lock; return the result."""
    resolved = layout or InstallationLayout()
    with file_transaction(resolved.assessment_record_path) as transaction:
        text = transaction.read_text(encoding=_TEXT_ENCODING)
        current = AssessmentRecord.model_validate_json(text) if text.strip() else AssessmentRecord()
        updated = transform(current)
        transaction.replace_text(updated.model_dump_json(), encoding=_TEXT_ENCODING)
    return updated


class AssessmentAnnouncer:
    """Announce the newest owed install at start and at a fixed interval while anything is owed."""

    def __init__(self, producer: EventProducer, layout: InstallationLayout, computer: str) -> None:
        self._producer = producer
        self._layout = layout
        self._computer = computer

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Announce now, then every interval until shutdown; a failed announcement never stops the loop."""
        while not shutdown_event.is_set():
            await self._announce()
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=_ANNOUNCE_INTERVAL_SECONDS)
                break
            except TimeoutError:
                pass

    async def _announce(self) -> None:
        """Emit the owed-assessment event for the newest owed install, when one is owed and the daemon is admitting."""
        if not get_shutdown_drain().is_open:
            # An announcement refused downstream would burn the event processor's retries; emit none while draining.
            return
        try:
            record = read_assessment(self._layout)
        except (OSError, ValidationError):
            logger.error(_READ_FAILED_EVENT, exc_info=True)
            return
        newest = record.newest_owed
        if newest is None:
            return
        try:
            await self._producer.emit(
                InstallationAssessmentOwed(
                    subject=InstallRef(_SUBJECT_IDENTITY.format(computer=self._computer, number=newest.number)),
                    home=EventHomeMarker.NONE,
                    data=InstallationAssessmentOwedData(
                        number=newest.number,
                        revision=newest.revision,
                        owed_since=newest.owed_since.isoformat(),
                        owed_count=len(record.owed),
                    ),
                ),
                LegacyFacts(
                    producer=_ANNOUNCEMENT_PRODUCER,
                    level=EventLevel.INFRASTRUCTURE,
                    domain=_ANNOUNCEMENT_DOMAIN,
                    visibility=EventVisibility.CLUSTER,
                    description=_ANNOUNCEMENT_DESCRIPTION.format(number=newest.number, computer=self._computer),
                ),
            )
        except Exception:  # supervision boundary: a failed announcement is repeated at the next interval
            logger.error(_ANNOUNCE_FAILED_EVENT, number=newest.number, revision=newest.revision, exc_info=True)
            return
        logger.info(_ANNOUNCED_EVENT, number=newest.number, revision=newest.revision, owed_count=len(record.owed))


def serving_active_release(layout: InstallationLayout | None = None) -> str | None:
    """Why the daemon does not serve the active release, or ``None`` when it does.

    The daemon serves it when its typed health reports the active release's revision as the commit it started
    from and an open admission phase — the same reading that verifies a start. A queued install or an accepted
    restart reports neither.
    """
    resolved = layout or InstallationLayout()
    active = resolved.active_revision()
    if active is None:
        return _NOT_SERVING_NO_ACTIVE
    try:
        health = asyncio.run(read_typed_health())
    except Exception as error:  # supervision boundary: any failure to read health means serving is not shown
        return _NOT_SERVING_UNREACHABLE.format(error_kind=type(error).__name__)
    if health.start_commit != active:
        serving = health.start_commit or _NOT_SERVING_UNKNOWN_START
        return _NOT_SERVING_OTHER_RELEASE.format(serving=serving, active=active)
    if health.preparation is None or health.preparation.phase is not DrainPhase.OPEN:
        return _NOT_SERVING_NOT_ADMITTING.format(active=active)
    return None

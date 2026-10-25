"""Installation event declarations: the assessment an install owes, authored by reconciliation.

The event states facts about the owed install only. The subject is the newest owed install; the event
states no origin, because the installation belongs to no registered project, person, or company.
"""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.references import InstallRef


class InstallationAssessmentOwedData(EventData):
    number: int
    revision: str
    owed_since: str
    owed_count: int


class InstallationAssessmentOwed(PlatformEvent[InstallRef, InstallationAssessmentOwedData]):
    NAME = "teleclaude.installation.assessment.owed"
    DESCRIPTION = "An install owes the assessment of the release that runs after it"
    RELATED_KINDS = ()


DECLARED: tuple[DeclaredEvent, ...] = (InstallationAssessmentOwed,)

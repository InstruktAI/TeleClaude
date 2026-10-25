"""Installation event declarations authored by reconciliation: the assessment an install owes and the release held.

The owed-assessment event states facts about the owed install only; its subject is the newest owed install.
The held-release event states facts about the published release the installation holds; its subject is that
release. Neither states an origin, because the installation belongs to no registered project, person, or company.
"""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.references import InstallRef, ReleaseRef


class InstallationAssessmentOwedData(EventData):
    number: int
    revision: str
    owed_since: str
    owed_count: int


class InstallationAssessmentOwed(PlatformEvent[InstallRef, InstallationAssessmentOwedData]):
    NAME = "teleclaude.installation.assessment.owed"
    DESCRIPTION = "An install owes the assessment of the release that runs after it"
    RELATED_KINDS = ()


class InstallationReleaseHeldData(EventData):
    source: str
    version: str
    tag: str
    active_version: str


class InstallationReleaseHeld(PlatformEvent[ReleaseRef, InstallationReleaseHeldData]):
    NAME = "teleclaude.installation.release.held"
    DESCRIPTION = "A published release beyond the active release's compatibility series is held for the inspector"
    RELATED_KINDS = ()


DECLARED: tuple[DeclaredEvent, ...] = (InstallationAssessmentOwed, InstallationReleaseHeld)

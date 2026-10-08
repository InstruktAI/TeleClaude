"""Schema evolution event declarations: the schema proposal is the subject."""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.references import SchemaProposalRef


class SchemaProposalData(EventData):
    """A schema event states everything in its type and subject."""


class SchemaProposed(PlatformEvent[SchemaProposalRef, SchemaProposalData]):
    NAME = "teleclaude.schema.proposed"
    DESCRIPTION = "A schema change was proposed for adoption"


class SchemaAdopted(PlatformEvent[SchemaProposalRef, SchemaProposalData]):
    NAME = "teleclaude.schema.adopted"
    DESCRIPTION = "A proposed schema change was merged and is now active"


DECLARED: tuple[DeclaredEvent, ...] = (SchemaProposed, SchemaAdopted)

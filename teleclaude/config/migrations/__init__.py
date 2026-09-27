"""Published configuration migration interfaces."""

from teleclaude.config.migrations._chain import (
    CURRENT_VERSION,
    Destination,
    DocumentNewerThanInstallation,
    MigrationTrigger,
    RegistrySubjectRequired,
    in_transit,
    upcast,
)
from teleclaude.config.migrations._registry import registered_subject, resolve_read_subject
from teleclaude.config.migrations._runner import (
    MigrationFailureReason,
    MigrationOutcome,
    carry_pending,
    migrate_document,
    migrate_registered,
)
from teleclaude.config.migrations.v003_relocate_person_invite_token import DestinationConflict
from teleclaude.config.migrations.v004_relocate_legacy_discord_provider_ids import HandoffConflict

__all__ = [
    "CURRENT_VERSION",
    "Destination",
    "DestinationConflict",
    "DocumentNewerThanInstallation",
    "HandoffConflict",
    "MigrationFailureReason",
    "MigrationOutcome",
    "MigrationTrigger",
    "RegistrySubjectRequired",
    "carry_pending",
    "in_transit",
    "migrate_document",
    "migrate_registered",
    "registered_subject",
    "resolve_read_subject",
    "upcast",
]

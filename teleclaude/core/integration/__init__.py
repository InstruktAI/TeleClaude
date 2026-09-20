"""Integration bounded-context contracts and workflows."""

from teleclaude.core.integration.discord_admin_state import (
    DiscordArtifactKind,
    DiscordProvider,
    DiscordReflectionOutcome,
    DiscordReflectionRecord,
    DiscordReflectionRepository,
    DiscordReflectionScope,
    DiscordScopeKind,
    DiscordVerificationResult,
)
from teleclaude.core.integration.lease import (
    IntegrationLeaseError,
    IntegrationLeaseStore,
    LeaseAcquireResult,
    LeaseAcquireStatus,
    LeaseRecord,
    LeaseRenewResult,
    LeaseRenewStatus,
)

__all__ = [
    "DiscordArtifactKind",
    "DiscordProvider",
    "DiscordReflectionOutcome",
    "DiscordReflectionRecord",
    "DiscordReflectionRepository",
    "DiscordReflectionScope",
    "DiscordScopeKind",
    "DiscordVerificationResult",
    "IntegrationLeaseError",
    "IntegrationLeaseStore",
    "LeaseAcquireResult",
    "LeaseAcquireStatus",
    "LeaseRecord",
    "LeaseRenewResult",
    "LeaseRenewStatus",
]

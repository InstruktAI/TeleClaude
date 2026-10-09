"""The immutable, statically declared configuration migration order."""

from __future__ import annotations

from typing import Final

from teleclaude.config.migrations import (
    v001_declare_tier_kind,
    v002_claim_person_slug,
    v003_relocate_person_invite_token,
    v004_relocate_legacy_discord_provider_ids,
    v005_retire_migration_records,
    v006_declare_machine_kind,
    v007_drop_business_domains,
    v008_declare_effective_capabilities,
    v009_fold_trusted_directories,
    v010_declare_help_desk,
    v011_retire_help_desk_dir,
    v012_restore_api_tcp_port,
    v013_declare_inbound_sources,
    v014_declare_maintenance_on_demand,
    v015_retire_event_domains,
    v016_declare_notification_interests,
)

STEPS: Final = (
    v001_declare_tier_kind,
    v002_claim_person_slug,
    v003_relocate_person_invite_token,
    v004_relocate_legacy_discord_provider_ids,
    v005_retire_migration_records,
    v006_declare_machine_kind,
    v007_drop_business_domains,
    v008_declare_effective_capabilities,
    v009_fold_trusted_directories,
    v010_declare_help_desk,
    v011_retire_help_desk_dir,
    v012_restore_api_tcp_port,
    v013_declare_inbound_sources,
    v014_declare_maintenance_on_demand,
    v015_retire_event_domains,
    v016_declare_notification_interests,
)

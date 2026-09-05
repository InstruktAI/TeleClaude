"""Delegate registered person workspace claim migration to config."""

from __future__ import annotations

from teleclaude.config.loader import load_global_config
from teleclaude.config.person_claim import migrate_person_claims, person_claims_complete


def check() -> bool:
    """Return whether the config-owned claim transition has completed."""
    return person_claims_complete()


def migrate() -> bool:
    """Advance every pending claim through the config-owned transition."""
    return migrate_person_claims(load_global_config().people)

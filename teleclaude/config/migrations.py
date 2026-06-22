"""One-shot config-domain migrations run before folder-keyed config access.

These live in the config domain so both daemon startup (``core.lifecycle``) and
the CLI people commands can invoke them without a core→cli dependency.
"""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.invitations import load_invitations, save_invitations
from teleclaude.config.loader import (
    _person_config_keys,
    load_global_config,
    normalize_person_config_key,
    save_global_config,
)
from teleclaude.config.schema import PersonEntry
from teleclaude.paths import PEOPLE_DIR
from teleclaude.slug import ensure_unique_slug, normalize_slug

logger = get_logger(__name__)

_person_slug_migration_done = False


def _find_legacy_folder(person: PersonEntry) -> Path | None:
    """Locate a person's existing workspace folder by its legacy (name/username) key."""
    if not PEOPLE_DIR.exists():
        return None
    keys = _person_config_keys(person)
    for entry in sorted(PEOPLE_DIR.iterdir()):
        if entry.is_dir() and normalize_person_config_key(entry.name) in keys:
            return entry
    return None


def migrate_person_slugs_if_needed() -> None:
    """Populate ``slug`` for slug-less people, rename their folder, and remap invitations.

    Idempotent and one-shot per process: already-slugged entries and their
    folders are left untouched. Uniqueness is resolved against both the
    people-list slug set (existing plus newly-assigned this pass) and the
    filesystem, so two names that normalize to the same slug still get distinct
    keys when no folder exists to disambiguate them.
    """
    global _person_slug_migration_done
    if _person_slug_migration_done:
        return

    config = load_global_config()
    people = config.people
    reserved: set[str] = {p.slug for p in people if p.slug}
    invitations = load_invitations()
    config_changed = False
    invitations_changed = False

    for person in people:
        if person.slug:
            continue
        base = normalize_slug(person.name) or normalize_slug(person.username or "") or "person"
        legacy_dir = _find_legacy_folder(person)
        slug = ensure_unique_slug(PEOPLE_DIR, base, reserved=reserved, exclude_dir=legacy_dir)
        reserved.add(slug)
        person.slug = slug
        config_changed = True

        slug_dir = PEOPLE_DIR / slug
        if legacy_dir is not None and legacy_dir != slug_dir and legacy_dir.exists() and not slug_dir.exists():
            legacy_dir.rename(slug_dir)

        legacy_keys = _person_config_keys(person)
        for token, holder in list(invitations.items()):
            if holder == slug:
                continue
            if holder == person.name or normalize_person_config_key(holder) in legacy_keys:
                invitations[token] = slug
                invitations_changed = True

    if config_changed:
        save_global_config(config)
    if invitations_changed:
        save_invitations(invitations)

    _person_slug_migration_done = True

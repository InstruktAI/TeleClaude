"""Person resource lookups, projections, and registry candidate construction."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.person_registry import with_person
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.config.resource_catalog import load_mapping, raw_people
from teleclaude.config.resource_contract import SubjectNotFound, SubjectView
from teleclaude.config.revision import view_revision
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import GLOBAL_CONFIG_PATH, PEOPLE_DIR, ConfigFileName
from teleclaude.slug import ensure_unique_slug, normalize_slug

_KIND_KEY = "kind"
_SCHEMA_VERSION_KEY = "schema_version"
_SLUG_KEY = "slug"
_NAME_KEY = "name"
_EMAIL_KEY = "email"
_ROLE_KEY = "role"
_USERNAME_KEY = "username"
IDENTITY_SECTION = "identity"
SETTINGS_SECTION = "settings"


def person_overlay_path(slug: str) -> Path:
    """Return a person's declared overlay path."""
    return PEOPLE_DIR / slug / ConfigFileName.OVERLAY


def person_init_lookup_key(fields: Mapping[str, object] | None) -> str | None:
    """Return the person key init will address, whether supplied or name-derived."""
    values = fields or {}
    requested_slug = values.get(_SLUG_KEY)
    if requested_slug:
        return str(requested_slug)
    name = values.get(_NAME_KEY)
    return normalize_slug(str(name)) if name else None


def person_is_registered(slug: str) -> bool:
    """Check the global registry without opening the person's overlay transaction."""
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        global_raw = load_mapping(transaction.read_text(), GLOBAL_CONFIG_PATH)
        return find_person_raw(raw_people(global_raw), slug) is not None


def find_person_raw(people: list[object], slug: str) -> dict[str, object] | None:  # guard: loose-dict - raw YAML config
    """Locate one raw person entry by slug in a raw `people` list."""
    for entry in people:
        if isinstance(entry, dict) and entry.get(_SLUG_KEY) == slug:
            return cast(dict[str, object], entry)  # guard: loose-dict - raw YAML config
    return None


def person_identity_section(
    entry_raw: Mapping[str, object],
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    return {key: value for key, value in entry_raw.items() if key != _SLUG_KEY}


def person_settings_section(
    overlay_raw: Mapping[str, object],
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    return {key: value for key, value in overlay_raw.items() if key not in (_KIND_KEY, _SLUG_KEY, _SCHEMA_VERSION_KEY)}


def person_revision(identity: Mapping[str, object], settings: Mapping[str, object]) -> str:
    return view_revision({IDENTITY_SECTION: identity, SETTINGS_SECTION: settings})


def person_view(
    slug: str,
    global_raw: Mapping[str, object],
    overlay_raw: Mapping[str, object],
) -> SubjectView:
    entry_raw = find_person_raw(raw_people(global_raw), slug)
    if entry_raw is None:
        raise SubjectNotFound(str(unregistered_referent(ReferentKind.PERSON, slug)))
    identity = person_identity_section(entry_raw)
    settings = person_settings_section(overlay_raw)
    return SubjectView(
        ref=SubjectRef(ConfigSubjectKind.PERSON, slug),
        sources=(GLOBAL_CONFIG_PATH, person_overlay_path(slug)),
        sections={IDENTITY_SECTION: identity, SETTINGS_SECTION: settings},
        read_only={},
        revision=person_revision(identity, settings),
    )


def append_person_candidate(
    global_raw: Mapping[str, object],
    *,
    name: str,
    email: str,
    role: object | None,
    username: object | None,
    requested_slug: object | None,
) -> tuple[str, dict[str, object]]:  # guard: loose-dict - raw YAML config
    """Build a validated-shape registry candidate with one newly allocated person."""
    people_raw = raw_people(global_raw)
    reserved = {str(entry[_SLUG_KEY]) for entry in people_raw if isinstance(entry, dict) and entry.get(_SLUG_KEY)}
    base_slug = normalize_slug(str(requested_slug)) if requested_slug else normalize_slug(name)
    slug = ensure_unique_slug(PEOPLE_DIR, base_slug, reserved=reserved)
    entry = PersonEntry.model_validate(
        {
            _NAME_KEY: name,
            _EMAIL_KEY: email,
            _SLUG_KEY: slug,
            **({_ROLE_KEY: role} if role else {}),
            **({_USERNAME_KEY: username} if username else {}),
        }
    )
    candidate_raw = with_person(cast(dict[object, object], global_raw), entry)
    candidate_document = {
        str(key): value for key, value in candidate_raw.items() if key != _KIND_KEY
    }  # guard: loose-dict - raw YAML config
    return slug, candidate_document

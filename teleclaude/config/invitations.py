"""Token-keyed JSON invitations store and the rules that write it.

Exposes read/write/delete operations for managing invitation tokens, and the
token-issuance/lookup rules that used to live in the CLI layer.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from hashlib import sha256

from instrukt_ai_logging import get_logger
from ruamel.yaml.error import YAMLError

from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.invitation_store import delete_invitation as _delete_invitation
from teleclaude.config.invitation_store import load_invitations, save_invitations
from teleclaude.config.loader import load_person_config
from teleclaude.config.migrations import Destination, MigrationOutcome, MigrationTrigger, in_transit, migrate_document
from teleclaude.config.schema import PersonConfig
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import PEOPLE_DIR, ConfigFileName

logger = get_logger(__name__)

_TOKEN_PREFIX = "inv_"
_TOKEN_BYTES = 8


def delete_invitation(token: str) -> None:
    """Delete an invitation by its token."""
    _delete_invitation(token)


def list_person_dirs() -> list[str]:
    """Scan ~/.teleclaude/people/ for person directories."""
    if not PEOPLE_DIR.exists():
        return []
    return sorted(d.name for d in PEOPLE_DIR.iterdir() if d.is_dir() and (d / ConfigFileName.OVERLAY).exists())


def generate_invite_token() -> str:
    """Generate a new invite token with format inv_{16_hex_chars}."""
    return f"{_TOKEN_PREFIX}{secrets.token_hex(_TOKEN_BYTES)}"


def issue_invite_token(slug: str) -> str:
    """Generate and persist a new invite token for the person slug. Returns the token."""
    person_path = PEOPLE_DIR / slug / ConfigFileName.OVERLAY
    record = migrate_document(
        person_path,
        SubjectRef(ConfigSubjectKind.PERSON, slug),
        MigrationTrigger.WRITER,
    )
    if record["outcome"] is MigrationOutcome.FAILED:
        raise ValueError(f"Could not migrate person configuration before issuing invite token: {record['reason']}")
    token = generate_invite_token()

    invitations = load_invitations()
    # Remove any existing tokens mapped to this person
    for existing_token, holder in list(invitations.items()):
        if holder == slug:
            del invitations[existing_token]

    invitations[token] = slug
    save_invitations(invitations)

    logger.info("Issued invite token for slug '%s'", slug)
    return token


def find_person_by_invite_token(token: str) -> tuple[str, PersonConfig] | None:
    """Resolve a token from its map or from a person's not-yet-delivered migration state."""
    invitations = load_invitations()
    mapped_owner = invitations.get(token)
    legacy_owners = _legacy_invitation_owners(token)
    if legacy_owners is None:
        return None
    if len(legacy_owners) > 1 or (mapped_owner is not None and any(owner != mapped_owner for owner in legacy_owners)):
        logger.warning(
            "invitation_token_conflicted",
            token_digest=sha256(token.encode("utf-8")).hexdigest(),
            claimant_count=len(legacy_owners | ({mapped_owner} if mapped_owner is not None else set())),
        )
        return None
    person_slug = mapped_owner or (next(iter(legacy_owners)) if legacy_owners else None)
    if person_slug is None:
        return None
    try:
        person_path = PEOPLE_DIR / person_slug / ConfigFileName.OVERLAY
        person_config = load_person_config(person_path, registered_slug=person_slug)
        return (person_slug, person_config)
    except (OSError, ValueError, KeyError) as error:
        logger.warning("Failed to load config for slug '%s': %s", person_slug, error)
        return None


def _legacy_invitation_owners(token: str) -> set[str] | None:
    """Read old invitation claims from person documents without writing them."""
    owners: set[str] = set()
    for slug in list_person_dirs():
        person_path = PEOPLE_DIR / slug / ConfigFileName.OVERLAY
        try:
            document: object = round_trip_yaml().load(person_path.read_text(encoding="utf-8"))
            if not isinstance(document, Mapping):
                continue
            pending = in_transit(document, SubjectRef(ConfigSubjectKind.PERSON, slug), Destination.INVITATIONS)
        except (OSError, ValueError, YAMLError) as error:
            logger.warning("Could not inspect pending invitation claim: %s", error)
            return None
        if token in pending:
            owners.add(slug)
    return owners

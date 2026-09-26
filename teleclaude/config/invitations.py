"""Token-keyed JSON invitations store and the rules that write it.

Exposes read/write/delete operations for managing invitation tokens, and the
token-issuance/lookup rules that used to live in the CLI layer.
"""

from __future__ import annotations

import json
import secrets

from instrukt_ai_logging import get_logger
from ruamel.yaml.error import YAMLError

from teleclaude.config._file_io import file_transaction
from teleclaude.config._file_migrations import move_person_invite_token
from teleclaude.config.loader import load_person_config
from teleclaude.config.schema import PersonConfig
from teleclaude.paths import INVITATIONS_PATH, PEOPLE_DIR, ConfigFileName

logger = get_logger(__name__)

_TOKEN_PREFIX = "inv_"
_TOKEN_BYTES = 8


def load_invitations() -> dict[str, str]:
    """Load the token-keyed invitations from invitations.json."""
    if not INVITATIONS_PATH.exists():
        return {}
    try:
        with open(INVITATIONS_PATH, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_invitations(invitations: dict[str, str]) -> None:
    """Save the token-keyed invitations to invitations.json atomically."""
    with file_transaction(INVITATIONS_PATH) as transaction:
        transaction.replace_text(json.dumps(invitations, indent=2) + "\n")


def delete_invitation(token: str) -> None:
    """Delete an invitation by its token."""
    invitations = load_invitations()
    if token in invitations:
        del invitations[token]
        save_invitations(invitations)


def list_person_dirs() -> list[str]:
    """Scan ~/.teleclaude/people/ for person directories."""
    if not PEOPLE_DIR.exists():
        return []
    return sorted(d.name for d in PEOPLE_DIR.iterdir() if d.is_dir() and (d / ConfigFileName.OVERLAY).exists())


def generate_invite_token() -> str:
    """Generate a new invite token with format inv_{16_hex_chars}."""
    return f"{_TOKEN_PREFIX}{secrets.token_hex(_TOKEN_BYTES)}"


_migration_done = False


def migrate_invitations_if_needed() -> None:
    """Perform one-shot migration of invite tokens from per-person configs to the invitations store."""
    global _migration_done
    if _migration_done:
        return

    for name in list_person_dirs():
        person_path = PEOPLE_DIR / name / ConfigFileName.OVERLAY
        if not person_path.exists():
            continue
        try:
            move_person_invite_token(person_path, name)
        except (OSError, ValueError, YAMLError) as e:
            logger.warning("Failed to migrate invite_token for person '%s': %s", name, e)
    _migration_done = True


def issue_invite_token(slug: str) -> str:
    """Generate and persist a new invite token for the person slug. Returns the token."""
    migrate_invitations_if_needed()
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
    """Find a person by their invite token using the O(1) invitations store. Returns (person_slug, config) or None."""
    migrate_invitations_if_needed()
    invitations = load_invitations()
    if token in invitations:
        person_slug = invitations[token]
        try:
            person_path = PEOPLE_DIR / person_slug / ConfigFileName.OVERLAY
            person_config = load_person_config(person_path, registered_slug=person_slug)
            return (person_slug, person_config)
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Failed to load config for slug '%s': %s", person_slug, e)
            return None
    return None

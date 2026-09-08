"""Token-keyed JSON invitations store.

Exposes read/write/delete operations for managing invitation tokens.
"""

from __future__ import annotations

import json

from teleclaude.config._file_io import file_transaction
from teleclaude.paths import INVITATIONS_PATH


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

"""Leaf storage owner for the token-keyed invitation map."""

from __future__ import annotations

import json

from teleclaude.config._file_io import file_transaction
from teleclaude.paths import INVITATIONS_PATH


class InvitationTokenOwned(ValueError):
    """An invitation token is already assigned to a different person."""


def load_invitations() -> dict[str, str]:
    """Load the token-keyed invitations from the state file."""
    if not INVITATIONS_PATH.exists():
        return {}
    try:
        data = json.loads(INVITATIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items()}
    return {}


def save_invitations(invitations: dict[str, str]) -> None:
    """Replace the token map atomically."""
    with file_transaction(INVITATIONS_PATH) as transaction:
        transaction.replace_text(json.dumps(invitations, indent=2) + "\n")


def delete_invitation(token: str) -> None:
    """Delete a token when it is present."""
    invitations = load_invitations()
    if token in invitations:
        del invitations[token]
        save_invitations(invitations)


def assign_token(token: str, slug: str) -> None:
    """Assign a token unless another person already owns it."""
    with file_transaction(INVITATIONS_PATH) as transaction:
        try:
            data = json.loads(transaction.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        invitations = {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}
        owner = invitations.get(token)
        if owner is not None and owner != slug:
            raise InvitationTokenOwned(f"Invitation token is already owned by '{owner}'")
        if owner == slug:
            return
        invitations[token] = slug
        transaction.replace_text(json.dumps(invitations, indent=2) + "\n")

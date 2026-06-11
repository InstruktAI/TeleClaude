"""Token-keyed JSON invitations store.

Exposes read/write/delete operations for managing invitation tokens.
"""

from __future__ import annotations

import fcntl
import json
import os

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
    INVITATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = INVITATIONS_PATH.with_suffix(".lock")
    tmp_path = INVITATIONS_PATH.with_suffix(".tmp")

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(invitations, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, INVITATIONS_PATH)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass


def delete_invitation(token: str) -> None:
    """Delete an invitation by its token."""
    invitations = load_invitations()
    if token in invitations:
        del invitations[token]
        save_invitations(invitations)

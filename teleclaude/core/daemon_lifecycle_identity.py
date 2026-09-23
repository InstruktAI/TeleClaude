"""Process-local credential the daemon presents on its own outbound calls."""

from __future__ import annotations

import secrets

DAEMON_CREDENTIAL_HEADER = "x-teleclaude-daemon-token"
_DAEMON_CREDENTIAL_VALUE = secrets.token_urlsafe(32)


def daemon_credential_headers() -> dict[str, str]:
    """Return the daemon's own identity header.

    The value is generated once per daemon process and is never persisted,
    logged, or exported into a child process environment, so no other
    process can produce a value that resolves.
    """
    return {DAEMON_CREDENTIAL_HEADER: _DAEMON_CREDENTIAL_VALUE}


def is_daemon_credential(candidate: str | None) -> bool:
    """Return whether *candidate* is this process's own credential value."""
    return candidate is not None and secrets.compare_digest(candidate, _DAEMON_CREDENTIAL_VALUE)


__all__ = ["DAEMON_CREDENTIAL_HEADER", "daemon_credential_headers", "is_daemon_credential"]

"""Process-local capability for the daemon's lifecycle UDS client."""

from __future__ import annotations

import secrets

_LIFECYCLE_HEADER = "x-teleclaude-daemon-lifecycle-token"
_LIFECYCLE_TOKEN = secrets.token_urlsafe(32)


def daemon_lifecycle_headers() -> dict[str, str]:
    """Return the daemon-only lifecycle authentication header.

    The capability is generated once per daemon process and is never persisted,
    logged, or exposed through a public request model.
    """

    return {_LIFECYCLE_HEADER: _LIFECYCLE_TOKEN}


def is_daemon_lifecycle_token(candidate: str | None) -> bool:
    """Return whether a supplied value is this process's lifecycle capability."""

    return candidate is not None and secrets.compare_digest(candidate, _LIFECYCLE_TOKEN)


__all__ = ["daemon_lifecycle_headers", "is_daemon_lifecycle_token"]

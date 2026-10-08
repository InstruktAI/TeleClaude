"""Process-local credential the daemon presents on its own outbound calls."""

from __future__ import annotations

import secrets

from teleclaude.core.shutdown_drain import CONTINUATION_HEADER, get_shutdown_drain

DAEMON_CREDENTIAL_HEADER = "x-teleclaude-daemon-token"
_DAEMON_CREDENTIAL_VALUE = secrets.token_urlsafe(32)


def daemon_credential_headers() -> dict[str, str]:
    """Return the daemon's own identity header.

    The value is generated once per daemon process and is never persisted,
    logged, or exported into a child process environment, so no other
    process can produce a value that resolves.

    A call made while the current context holds accepted work also carries that
    work's continuation capability, so the daemon's self-call is admitted as the
    continuation it is while a draining daemon refuses everything else.
    """
    headers = {DAEMON_CREDENTIAL_HEADER: _DAEMON_CREDENTIAL_VALUE}
    capability = get_shutdown_drain().issue_continuation()
    if capability is not None:
        headers[CONTINUATION_HEADER] = capability
    return headers


def is_daemon_credential(candidate: str | None) -> bool:
    """Return whether *candidate* is this process's own credential value."""
    return candidate is not None and secrets.compare_digest(candidate, _DAEMON_CREDENTIAL_VALUE)


__all__ = ["DAEMON_CREDENTIAL_HEADER", "daemon_credential_headers", "is_daemon_credential"]

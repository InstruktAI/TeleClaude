"""GitHub payload normalizer."""

from __future__ import annotations

from typing import Final

from teleclaude.hooks.webhook_models import HookEvent

GITHUB_SOURCE: Final = "github"
_EVENT_HEADER: Final = "x-github-event"
_UNKNOWN_EVENT: Final = "unknown"


# guard: loose-dict-func - GitHub webhook payload is third-party JSON.
def _get_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    return None


# guard: loose-dict-func - GitHub webhook payload is third-party JSON.
def _get_repo_full_name(payload: dict[str, object]) -> str | None:
    repo = payload.get("repository")
    if not isinstance(repo, dict):
        return None
    full_name = repo.get("full_name")
    if isinstance(full_name, str):
        return full_name
    return None


# guard: loose-dict-func - GitHub webhook payload is third-party JSON.
def _get_sender_login(payload: dict[str, object]) -> str | None:
    sender = payload.get("sender")
    if not isinstance(sender, dict):
        return None
    login = sender.get("login")
    return login if isinstance(login, str) else None


# guard: loose-dict-func - GitHub webhook payload is third-party JSON.
def github_hook_event(event_type: str, payload: dict[str, object], timestamp: str) -> HookEvent:
    """Build the canonical GitHub HookEvent for one delivery's event type and body."""
    action = _get_str(payload, "action")
    ref = _get_str(payload, "ref")
    zen = _get_str(payload, "zen")

    properties: dict[str, str | int | float | bool | list[str] | None] = {
        "repo": _get_repo_full_name(payload),
        "sender": _get_sender_login(payload),
        "action": action,
        "ref": ref,
    }

    if event_type == "ping":
        hook_id = payload.get("hook_id")
        if zen is not None:
            properties["zen"] = zen
        if isinstance(hook_id, int | str):
            properties["hook_id"] = hook_id

    return HookEvent(source=GITHUB_SOURCE, type=event_type, timestamp=timestamp, properties=properties, payload=payload)


def github_event_type(headers: dict[str, str]) -> str:
    """Return GitHub's event type for a delivery from its lowercased-name headers, or the unknown type when absent."""
    return (headers.get(_EVENT_HEADER) or _UNKNOWN_EVENT).lower()

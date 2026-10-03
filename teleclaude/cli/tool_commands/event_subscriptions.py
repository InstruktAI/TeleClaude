"""CLI API calls for caller-session event subscriptions."""

from __future__ import annotations

from typing import TypedDict
from urllib.parse import quote

from pydantic import JsonValue

from teleclaude.cli.tool_client import tool_api_call

_GET = "GET"
_POST = "POST"
_DELETE = "DELETE"
_EVENT_SUBSCRIPTIONS_PATH = "/event-subscriptions"
_PATH_SEPARATOR = "/"


class EventSubscriptionRequestBody(TypedDict):
    """Validated subscription data sent to the daemon API."""

    event_type: str
    once: bool
    narrowing: dict[str, JsonValue]


def subscribe(body: EventSubscriptionRequestBody) -> object:
    """Create one event subscription for the authenticated caller session."""
    return tool_api_call(_POST, _EVENT_SUBSCRIPTIONS_PATH, json_body=body)


def list_subscriptions() -> object:
    """Read the authenticated caller session's live event subscriptions."""
    return tool_api_call(_GET, _EVENT_SUBSCRIPTIONS_PATH)


def unsubscribe(subscription_id: str) -> object:
    """Withdraw one event subscription owned by the authenticated caller."""
    path = _EVENT_SUBSCRIPTIONS_PATH + _PATH_SEPARATOR + quote(subscription_id, safe="")
    return tool_api_call(_DELETE, path)

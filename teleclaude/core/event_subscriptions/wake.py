"""Render the event notification body carried through control delivery."""

from __future__ import annotations

import json

from pydantic import JsonValue

from teleclaude.core.db_models import EventSubscriptionRow
from teleclaude.events.envelope import EventEnvelope, subject_owner_token, subject_token

_WAKE_EVENT_KEY = "event"
_WAKE_EVENT_ID_KEY = "event_id"
_WAKE_TIMESTAMP_KEY = "timestamp"
_WAKE_ORIGIN_KEY = "origin"
_WAKE_COMPUTER_KEY = "computer"
_WAKE_SESSION_KEY = "session_id"
_WAKE_HOME_KEY = "home"
_WAKE_SUBJECT_KEY = "subject"
_WAKE_SUBJECT_OWNER_KEY = "subject_owner"
_WAKE_SUBSCRIPTION_ID_KEY = "subscription_id"
_WAKE_MODE_KEY = "mode"
_WAKE_PAYLOAD_KEY = "payload"
_JSON_INDENT = 2


def render_wake_body(envelope: EventEnvelope, subscription: EventSubscriptionRow) -> str:
    """Render the source event and subscription identity as one JSON body."""
    origin: dict[str, JsonValue] = {}
    if envelope.originating_computer is not None:
        origin[_WAKE_COMPUTER_KEY] = envelope.originating_computer
    if envelope.originating_session_id is not None:
        origin[_WAKE_SESSION_KEY] = envelope.originating_session_id
    if envelope.origin_home is not None:
        origin[_WAKE_HOME_KEY] = envelope.origin_home.to_token()

    body: dict[str, JsonValue] = {
        _WAKE_EVENT_KEY: envelope.event,
        _WAKE_EVENT_ID_KEY: envelope.event_id,
        _WAKE_TIMESTAMP_KEY: envelope.timestamp.isoformat(),
        _WAKE_ORIGIN_KEY: origin,
        _WAKE_SUBJECT_KEY: subject_token(envelope.subject),
        _WAKE_SUBJECT_OWNER_KEY: subject_owner_token(envelope.subject_owner),
        _WAKE_SUBSCRIPTION_ID_KEY: subscription.id,
        _WAKE_MODE_KEY: subscription.mode,
        _WAKE_PAYLOAD_KEY: envelope.payload,
    }
    return json.dumps(body, ensure_ascii=False, indent=_JSON_INDENT)

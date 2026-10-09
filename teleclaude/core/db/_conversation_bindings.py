"""Database adapter for the mesh master's durable conversation bindings."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from teleclaude.core import db_models
from teleclaude.core.models import EndpointStamp

# The binding's conversation key, and the columns a newer binding replaces.
_BINDING_KEY_COLUMNS = ("origin", "key_field", "conversation_key")
_BINDING_REPLACED_COLUMNS = ("session_id", "endpoint", "entered_at")
_INVALID_ENDPOINT_ERROR = "conversation binding for session {session_id} has no valid endpoint"


@dataclass(frozen=True)
class ConversationBinding:
    """One shared-adapter conversation's binding: the session its next message goes to."""

    origin: str
    key_field: str
    conversation_key: str
    session_id: str
    endpoint: EndpointStamp
    entered_at: str


class DbConversationBindingsMixin:
    """Persist the master's conversation bindings."""

    async def get_conversation_binding(
        self, origin: str, key_field: str, conversation_key: str
    ) -> ConversationBinding | None:
        """Read one conversation's binding."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.ConversationBindingRow, (origin, key_field, conversation_key))
        return _to_binding(row) if row is not None else None

    async def put_conversation_binding(self, binding: ConversationBinding) -> None:
        """Record a conversation's binding in one write, replacing any earlier one."""
        statement = sqlite_insert(db_models.ConversationBindingRow).values(
            origin=binding.origin,
            key_field=binding.key_field,
            conversation_key=binding.conversation_key,
            session_id=binding.session_id,
            endpoint=json.dumps(binding.endpoint.to_dict()),
            entered_at=binding.entered_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=list(_BINDING_KEY_COLUMNS),
            set_={column: statement.excluded[column] for column in _BINDING_REPLACED_COLUMNS},
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def delete_conversation_binding(self, origin: str, key_field: str, conversation_key: str) -> None:
        """Forget one conversation's binding."""
        async with self._session() as db_session:
            await db_session.exec(
                delete(db_models.ConversationBindingRow).where(
                    db_models.ConversationBindingRow.origin == origin,  # type: ignore[arg-type]
                    db_models.ConversationBindingRow.key_field == key_field,  # type: ignore[arg-type]
                    db_models.ConversationBindingRow.conversation_key == conversation_key,  # type: ignore[arg-type]
                )
            )
            await db_session.commit()


def _to_binding(row: db_models.ConversationBindingRow) -> ConversationBinding:
    stored: object = json.loads(row.endpoint)
    endpoint = EndpointStamp.from_dict(stored) if isinstance(stored, dict) else None
    if endpoint is None:
        raise ValueError(_INVALID_ENDPOINT_ERROR.format(session_id=row.session_id))
    return ConversationBinding(
        origin=row.origin,
        key_field=row.key_field,
        conversation_key=row.conversation_key,
        session_id=row.session_id,
        endpoint=endpoint,
        entered_at=row.entered_at,
    )


__all__ = [
    "ConversationBinding",
    "DbConversationBindingsMixin",
]

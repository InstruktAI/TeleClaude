"""Database package for TeleClaude.

Re-exports all public names from submodules for backward compatibility.
The Db class is assembled here via mixin inheritance.
"""

from __future__ import annotations

import asyncio

from teleclaude.paths import MAIN_DB_PATH

from ._base import DbBase
from ._conversation_delivery import (
    DbConversationDeliveryMixin,
    PeerBundleSegmentInput,
    PeerBundleSegmentRecord,
    PeerBundleWithSegments,
)
from ._hooks import DbHooksMixin
from ._inbound import (
    AcceptedTurnBindingRecord,
    DbInboundMixin,
    NativeReference,
    TurnAuthoredPartInput,
    TurnAuthoredPartRecord,
)
from ._links import DbLinksMixin
from ._listeners import DbListenersMixin
from ._operations import DbOperationsMixin
from ._output_generations import DbOutputGenerationsMixin, DiscordSendIntent, OutputGeneration
from ._process_lifecycle import DbProcessLifecycleMixin
from ._reminders import DbRemindersMixin
from ._rows import HookOutboxRow, InboundQueueRow, OperationRow
from ._sessions import DbSessionsMixin
from ._settings import DbSettingsMixin
from ._sync import (
    SessionIdentityError,
    delete_process_spawn_registry_entry_sync,
    get_process_spawn_registry_entry_sync,
    get_session_field_sync,
    get_session_id_by_field_sync,
    get_session_id_by_tmux_name_sync,
    read_agent_availability_sync,
    replace_process_spawn_registry_entry_sync,
    resolve_session_principal,
)
from ._tokens import DbTokensMixin
from ._voice_transcriptions import DbVoiceTranscriptionsMixin
from ._webhooks import DbWebhooksMixin


class Db(
    DbRemindersMixin,
    DbConversationDeliveryMixin,
    DbTokensMixin,
    DbLinksMixin,
    DbListenersMixin,
    DbWebhooksMixin,
    DbOperationsMixin,
    DbOutputGenerationsMixin,
    DbInboundMixin,
    DbHooksMixin,
    DbProcessLifecycleMixin,
    DbSettingsMixin,
    DbVoiceTranscriptionsMixin,
    DbSessionsMixin,
    DbBase,
):
    """Database interface for tmux sessions and state management."""


_lock = asyncio.Lock()

# Transitional module-level instance. The daemon bootstraps this at startup via
# ``await db.initialize()``; CLI consumers must instead use ``get_db()`` so the
# instance is always initialized when handed out. New code should call
# ``get_db()``; ``db`` remains exported for in-flight migration of the existing
# daemon-side consumers and will be removed once those are migrated.
db = Db(str(MAIN_DB_PATH))


async def get_db() -> Db:
    """Return the process-wide initialized Db instance, creating it on first call.

    Daemon, CLI, and test contexts reach the main session DB through this
    factory. Construction is async (schema bootstrap and migrations require
    aiosqlite), so module-level instantiation alone cannot suffice. Memoized
    per process via the shared module instance; safe under concurrent
    first-callers via the lock.
    """
    if not db.is_initialized():
        async with _lock:
            if not db.is_initialized():
                await db.initialize()
    return db


__all__ = [
    "AcceptedTurnBindingRecord",
    "Db",
    "DiscordSendIntent",
    "HookOutboxRow",
    "InboundQueueRow",
    "NativeReference",
    "OperationRow",
    "OutputGeneration",
    "PeerBundleSegmentInput",
    "PeerBundleSegmentRecord",
    "PeerBundleWithSegments",
    "SessionIdentityError",
    "TurnAuthoredPartInput",
    "TurnAuthoredPartRecord",
    "db",
    "delete_process_spawn_registry_entry_sync",
    "get_db",
    "get_process_spawn_registry_entry_sync",
    "get_session_field_sync",
    "get_session_id_by_field_sync",
    "get_session_id_by_tmux_name_sync",
    "read_agent_availability_sync",
    "replace_process_spawn_registry_entry_sync",
    "resolve_session_principal",
]

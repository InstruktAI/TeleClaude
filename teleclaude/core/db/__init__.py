"""Database package for TeleClaude.

Re-exports all public names from submodules for backward compatibility.
The Db class is assembled here via mixin inheritance.
"""

from teleclaude.paths import MAIN_DB_PATH

from ._base import DbBase
from ._conversation_delivery import DbConversationDeliveryMixin
from ._hooks import DbHooksMixin
from ._inbound import DbInboundMixin
from ._links import DbLinksMixin
from ._listeners import DbListenersMixin
from ._operations import DbOperationsMixin
from ._rows import HookOutboxRow, InboundQueueRow, OperationRow
from ._sessions import DbSessionsMixin
from ._settings import DbSettingsMixin
from ._sync import (
    SessionIdentityError,
    get_session_field_sync,
    get_session_id_by_field_sync,
    get_session_id_by_tmux_name_sync,
    resolve_session_principal,
)
from ._tokens import DbTokensMixin
from ._webhooks import DbWebhooksMixin


class Db(  # pylint: disable=too-many-ancestors  # The DB facade is intentionally composed from focused mixins.
    DbConversationDeliveryMixin,
    DbTokensMixin,
    DbLinksMixin,
    DbListenersMixin,
    DbWebhooksMixin,
    DbOperationsMixin,
    DbInboundMixin,
    DbHooksMixin,
    DbSettingsMixin,
    DbSessionsMixin,
    DbBase,
):
    """Database interface for tmux sessions and state management."""


# Module-level singleton instance (initialized on first import)
db = Db(str(MAIN_DB_PATH))


__all__ = [
    # Db class
    "Db",
    # TypedDict rows
    "HookOutboxRow",
    "InboundQueueRow",
    "OperationRow",
    "SessionIdentityError",
    # Singleton
    "db",
    # Sync helpers
    "get_session_field_sync",
    "get_session_id_by_field_sync",
    "get_session_id_by_tmux_name_sync",
    "resolve_session_principal",
]

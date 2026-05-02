"""Runtime domain protocols — reader/writer contracts for session state and operations.

These protocols define the service interface for the runtime schema pillar.
Runtime sessions are ephemeral: open sessions are never auto-closed; closed
sessions are purged 7 days after ``closed_at`` (see
``maintenance_service._cleanup_inactive_sessions``). The ledger holds the
permanent history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class RuntimeReader(Protocol):
    """Read-only operations on runtime session state."""

    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    async def list_sessions(
        self,
        *,
        include_closed: bool = False,
        computer_name: str | None = None,
        agent: str | None = None,
        human_email: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def get_session_by_native_id(self, agent: str, native_session_id: str) -> dict[str, Any] | None: ...

    async def find_session_by_tmux(self, tmux_session_name: str) -> dict[str, Any] | None: ...

    async def session_exists(self, session_id: str) -> bool: ...

    # -- operations -----------------------------------------------------------

    async def get_operation(self, operation_id: str) -> dict[str, Any] | None: ...

    # -- tokens ---------------------------------------------------------------

    async def validate_token(self, token: str) -> dict[str, Any] | None: ...

    # -- settings -------------------------------------------------------------

    async def get_setting(self, key: str) -> str | None: ...


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class RuntimeWriter(Protocol):
    """Write operations on runtime state. May emit lifecycle events."""

    # -- session mutations ----------------------------------------------------

    async def create_session(
        self,
        session_id: str,
        *,
        computer_name: str,
        agent: str,
        project_name: str | None = None,
        project_root: str | None = None,
        title: str | None = None,
        principal: str | None = None,
        human_email: str | None = None,
        initiator_session_id: str | None = None,
        origin_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def update_session(
        self,
        session_id: str,
        **fields: Any,
    ) -> None: ...

    async def close_session(
        self,
        session_id: str,
        *,
        closed_at: datetime | None = None,
    ) -> None: ...

    async def set_native_session_id(self, session_id: str, native_session_id: str) -> None: ...

    async def update_last_activity(self, session_id: str, timestamp: datetime) -> None: ...

    # -- operations -----------------------------------------------------------

    async def create_operation(
        self,
        operation_id: str,
        *,
        session_id: str | None = None,
        command_type: str,
        cwd: str,
        slug: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def complete_operation(self, operation_id: str, result: str) -> None: ...

    async def fail_operation(self, operation_id: str, error: str) -> None: ...

    # -- tokens ---------------------------------------------------------------

    async def issue_token(
        self,
        session_id: str,
        principal: str,
        role: str,
    ) -> str: ...

    async def revoke_session_tokens(self, session_id: str) -> None: ...

    # -- settings -------------------------------------------------------------

    async def set_setting(self, key: str, value: str) -> None: ...

    # -- cleanup --------------------------------------------------------------

    async def cleanup_expired_sessions(self, older_than: datetime) -> int: ...

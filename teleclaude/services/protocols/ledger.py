"""Ledger domain protocols — reader/writer contracts for session history.

The ledger is the permanent session archive. Native session ID is the
primary key. Consumers read structured blocks, never raw transcripts.
"""
# pylint: disable=missing-function-docstring,too-many-arguments

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class LedgerReader(Protocol):
    """Read-only operations on the permanent session archive."""

    async def get_session(self, native_id: str) -> dict[str, Any] | None: ...

    async def list_sessions(
        self,
        *,
        agent: str | None = None,
        project: str | None = None,
        human_email: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    async def search(
        self,
        query: str,
        *,
        agent: str | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...

    async def get_blocks(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
        block_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    async def get_session_summary(self, native_id: str) -> str | None: ...

    async def get_recent_summaries(
        self,
        *,
        human_email: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class LedgerWriter(Protocol):
    """Write operations on the session archive. Append-only for blocks."""

    async def upsert_session(
        self,
        native_id: str,
        *,
        agent: str,
        computer: str = "",
        project: str = "",
        human_email: str | None = None,
        title: str = "",
        summary: str | None = None,
        started_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def append_blocks(
        self,
        session_id: str,
        blocks: list[dict[str, Any]],
    ) -> int: ...

    async def update_summary(self, native_id: str, summary: str) -> None: ...

    async def update_projection_state(
        self,
        session_id: str,
        *,
        last_projected_seq: int,
        source_watermark: str | None = None,
        is_dirty: bool = False,
    ) -> None: ...

    async def mark_dirty(self, session_id: str) -> None: ...

    async def get_dirty_sessions(self) -> list[str]: ...

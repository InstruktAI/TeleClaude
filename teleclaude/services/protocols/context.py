"""Context domain protocols — reader/writer contracts for snippets and memories.

Snippets are read-only reflections of git-tracked files, synced by the
file watcher. Memories are durable observations scraped from sessions.
"""
# pylint: disable=missing-function-docstring,too-many-arguments

from __future__ import annotations

from typing import Any, Protocol


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class ContextReader(Protocol):
    """Read-only operations on context data (snippets and memories)."""

    # -- snippet reads --------------------------------------------------------

    async def index_snippets(
        self,
        *,
        project: str | None = None,
        domain: str | None = None,
        scope: str | None = None,
        snippet_type: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def get_snippets(self, ids: list[str]) -> list[dict[str, Any]]: ...

    async def search_snippets(
        self, query: str, *, project: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]: ...

    # -- memory reads ---------------------------------------------------------

    async def search_memories(
        self,
        query: str,
        *,
        project: str | None = None,
        person_email: str | None = None,
        observation_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    async def list_memories(
        self,
        *,
        project: str | None = None,
        observation_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    async def get_memory(self, memory_id: int) -> dict[str, Any] | None: ...

    async def get_memory_timeline(
        self,
        anchor_id: int,
        *,
        before: int = 3,
        after: int = 3,
        project: str | None = None,
    ) -> list[dict[str, Any]]: ...


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class ContextWriter(Protocol):
    """Write operations on context data."""

    # -- snippet sync (called by file watcher) --------------------------------

    async def upsert_snippet(
        self,
        snippet_id: str,
        *,
        project: str,
        domain: str = "",
        scope: str = "",
        snippet_type: str = "",
        description: str = "",
        content: str = "",
        file_path: str | None = None,
        frontmatter: dict[str, Any] | None = None,
    ) -> None: ...

    async def delete_snippet(self, snippet_id: str) -> bool: ...

    async def sync_project_snippets(
        self,
        project: str,
        snippets: list[dict[str, Any]],
    ) -> dict[str, int]: ...

    # -- memory mutations (called by scraper/CLI) -----------------------------

    async def save_memory(
        self,
        observation: str,
        *,
        project: str = "",
        person_email: str | None = None,
        title: str = "",
        observation_type: str = "context",
        source_session: str | None = None,
    ) -> int: ...

    async def delete_memory(self, memory_id: int) -> bool: ...

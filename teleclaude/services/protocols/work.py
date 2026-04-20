"""Work domain protocols — reader/writer contracts for todos, roadmap, artifacts.

These protocols define the service interface for the work schema pillar.
Implementations may target SQLite (current) or Postgres (target).
Callers (CLI, API, daemon) import these protocols — never the implementation.
"""

from __future__ import annotations

from typing import Any, Protocol

type StateValue = str | int | float | bool | None | dict[str, Any] | list[Any]  # guard: loose-dict


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class WorkReader(Protocol):
    """Read-only operations on the work domain."""

    # -- roadmap reads --------------------------------------------------------

    async def list_roadmap(
        self,
        *,
        domain: str | None = None,
        include_icebox: bool = False,
        include_delivered: bool = False,
    ) -> list[dict[str, Any]]: ...

    async def get_roadmap_entry(self, slug: str) -> dict[str, Any] | None: ...

    async def get_dependencies(self, slug: str) -> list[str]: ...

    async def get_dependents(self, slug: str) -> list[str]: ...

    async def get_all_dependencies(self) -> dict[str, list[str]]: ...

    async def delivered_slugs(self) -> set[str]: ...

    # -- todo state reads -----------------------------------------------------

    async def get_todo(self, slug: str) -> dict[str, StateValue] | None: ...

    async def list_slugs(self) -> list[str]: ...

    async def is_bug_todo(self, slug: str) -> bool: ...

    async def has_pending_deferrals(self, slug: str) -> bool: ...

    # -- artifact reads -------------------------------------------------------

    async def read_artifact(self, slug: str, name: str) -> str: ...

    async def artifact_exists(self, slug: str, name: str) -> bool: ...

    async def artifact_digest(self, slug: str, name: str) -> str: ...

    async def list_artifacts(self, slug: str) -> list[str]: ...

    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[dict[str, Any]]: ...


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class WorkWriter(Protocol):
    """Write operations on the work domain. May emit events on state changes."""

    # -- roadmap mutations ----------------------------------------------------

    async def add_roadmap_entry(
        self,
        slug: str,
        *,
        domain: str = "sdlc",
        description: str = "",
        kind: str = "feature",
        group: str | None = None,
        before: str | None = None,
        after: str | None = None,
        parent_id: str | None = None,
    ) -> str: ...

    async def remove_roadmap_entry(self, slug: str) -> bool: ...

    async def move_roadmap_entry(self, slug: str, *, before: str | None = None, after: str | None = None) -> bool: ...

    async def set_dependencies(self, slug: str, *, after: list[str]) -> None: ...

    async def freeze(self, slug: str) -> bool: ...

    async def unfreeze(self, slug: str) -> bool: ...

    async def deliver(self, slug: str, *, commit: str | None = None) -> bool: ...

    # -- todo state mutations -------------------------------------------------

    async def write_state(self, slug: str, state: dict[str, StateValue]) -> None: ...

    async def delete_state(self, slug: str) -> None: ...

    # -- artifact mutations ---------------------------------------------------

    async def write_artifact(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
    ) -> None: ...

    async def delete_artifacts(self, slug: str) -> None: ...

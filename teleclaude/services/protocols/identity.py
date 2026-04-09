"""Identity domain protocols — reader/writer contracts for people and credentials.

People are domain entities with roles, credentials across platforms,
and profiles that drive attunement and memory extraction.
"""
# pylint: disable=missing-function-docstring,too-many-arguments

from __future__ import annotations

from typing import Any, Protocol


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class IdentityReader(Protocol):
    """Read-only operations on identity data."""

    async def get_person_by_email(self, email: str) -> dict[str, Any] | None: ...

    async def get_person_by_name(self, name: str) -> dict[str, Any] | None: ...

    async def list_people(self) -> list[dict[str, Any]]: ...

    async def get_credentials(self, person_id: int, platform: str | None = None) -> list[dict[str, Any]]: ...

    async def find_person_by_platform(self, platform: str, platform_user_id: str) -> dict[str, Any] | None: ...

    async def get_role(self, email: str) -> str | None: ...


# guard: loose-dict-func - v2 protocol stub, row shapes TBD
class IdentityWriter(Protocol):
    """Write operations on identity data."""

    async def add_person(
        self,
        name: str,
        email: str,
        role: str = "newcomer",
        *,
        profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def update_person(
        self,
        name: str,
        *,
        email: str | None = None,
        role: str | None = None,
        profile: dict[str, Any] | None = None,
    ) -> None: ...

    async def remove_person(self, name: str) -> bool: ...

    async def add_credential(
        self,
        person_id: int,
        platform: str,
        *,
        platform_user_id: str | None = None,
        platform_username: str | None = None,
        platform_chat_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def remove_credential(self, person_id: int, platform: str) -> bool: ...

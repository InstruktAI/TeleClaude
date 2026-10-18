"""Authenticated GitHub REST account reads, without credential selection."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

_ACCOUNT_URL = "https://api.github.com/users/{handle}"
_EMPTY = ""
_AUTHORIZATION_HEADER = "authorization"
_ACCEPT_HEADER = "Accept"
_ACCEPT_JSON = "application/vnd.github+json"
_VERSION_HEADER = "X-GitHub-Api-Version"
_API_VERSION = "2026-03-10"
_LOOKUP_REFUSED = "Authenticated GitHub account lookup could not be verified"


class GitHubAccountKind(StrEnum):
    """Provider account types carried by REST author/account facts."""

    USER = "User"
    BOT = "Bot"
    ORGANIZATION = "Organization"


class GitHubAccount(BaseModel):
    """Stable provider identity; login is presentation and lookup input."""

    model_config = ConfigDict(frozen=True)

    id: int = Field(gt=0, strict=True)
    node_id: str = Field(min_length=1)
    login: str = Field(min_length=1)
    type: GitHubAccountKind

    def same_account(self, other: GitHubAccount) -> bool:
        """Compare stable provider facts independently of login spelling."""
        return self.id == other.id and self.node_id == other.node_id and self.type is other.type


class GitHubAccountLookupRefused(RuntimeError):
    """The provider lookup yielded no authenticated account fact."""


class GitHubAccountDirectory:
    """Read accounts through an already authenticated provider client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def read(self, handle: str) -> GitHubAccount:
        """Resolve one declared handle without redirects or native-login fallback."""
        url = _ACCOUNT_URL.format(handle=quote(handle, safe=_EMPTY))
        try:
            response = await self._client.get(
                url,
                headers={_ACCEPT_HEADER: _ACCEPT_JSON, _VERSION_HEADER: _API_VERSION},
                follow_redirects=False,
            )
            response.raise_for_status()
            if not response.request.headers.get(_AUTHORIZATION_HEADER):
                raise GitHubAccountLookupRefused(_LOOKUP_REFUSED)
            account = GitHubAccount.model_validate(response.json())
        except (httpx.HTTPError, ValueError):
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED) from None
        if account.login.casefold() != handle.casefold():
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED)
        return account

"""Authenticated GitHub REST account reads, without credential selection."""

from __future__ import annotations

from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.exception import GitHubException
from githubkit.github import GitHub

from teleclaude.types.github_account import GitHubAccount

_LOOKUP_REFUSED = "Authenticated GitHub account lookup could not be verified"
_EMPTY = ""
_GITHUB_API_URL = "https://api.github.com/"


class GitHubAccountLookupRefused(RuntimeError):
    """The provider lookup yielded no authenticated account fact."""


class GitHubAccountDirectory:
    """Read accounts through an already authenticated provider client."""

    def __init__(self, client: GitHub[TokenAuthStrategy]) -> None:
        self._client = client

    async def read(self, handle: str) -> GitHubAccount:
        """Resolve one declared handle without redirects or native-login fallback."""
        try:
            if (
                not self._client.auth.token
                or self._client.config.follow_redirects
                or str(self._client.config.base_url) != _GITHUB_API_URL
            ):
                raise GitHubAccountLookupRefused(_LOOKUP_REFUSED)
            response = await self._client.rest.users.async_get_by_username(quote(handle, safe=_EMPTY))
            if response.status_code != 200:
                raise GitHubAccountLookupRefused(_LOOKUP_REFUSED)
            account = GitHubAccount.model_validate(response.json())
        except (GitHubException, ValueError):
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED) from None
        if account.login.casefold() != handle.casefold():
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED)
        return account

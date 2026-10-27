"""Authenticated GitHub REST account reads, without credential selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.exception import GitHubException, RateLimitExceeded
from githubkit.github import GitHub

from teleclaude.github.rate_limit_headers import named_resume_time
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind

_LOOKUP_REFUSED = "Authenticated GitHub account lookup could not be verified"
_EMPTY = ""
_GITHUB_API_URL = "https://api.github.com/"


@dataclass(frozen=True)
class GitHubRateLimitFacts:
    """SDK recovery facts without its secret-bearing request/response objects.

    ``retry_after`` is the SDK's own delay, which it defaults when a response names none; ``resume_at`` is the time
    the response itself names, or None when it names none.
    """

    status_code: int
    retry_after: timedelta
    resume_at: datetime | None = None

    @classmethod
    def from_sdk(cls, error: RateLimitExceeded) -> Self:
        """Copy only public status, delay and named resume time; retain no raw SDK exception."""
        return cls(
            status_code=error.response.status_code,
            retry_after=error.retry_after,
            resume_at=named_resume_time(error.response.headers, datetime.now(UTC)),
        )


class GitHubAccountLookupRefused(RuntimeError):
    """The provider lookup yielded no authenticated account fact."""

    def __init__(self, message: str, *, rate_limit: GitHubRateLimitFacts | None = None) -> None:
        super().__init__(message)
        self.rate_limit = rate_limit


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
            provider = response.parsed_data
            account = GitHubAccount(
                id=provider.id,
                node_id=provider.node_id,
                login=provider.login,
                type=GitHubAccountKind(provider.type),
            )
        except RateLimitExceeded as error:
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED, rate_limit=GitHubRateLimitFacts.from_sdk(error)) from None
        except (GitHubException, ValueError):
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED) from None
        if account.login.casefold() != handle.casefold():
            raise GitHubAccountLookupRefused(_LOOKUP_REFUSED)
        return account

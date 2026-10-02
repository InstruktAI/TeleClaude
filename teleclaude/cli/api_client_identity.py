"""Identity self-query surface for the TeleClaude API client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPMethod

import httpx

from teleclaude.api_models_identity import WhoAmIDTO

_AUTH_WHOAMI_ROUTE = "/auth/whoami"


class TelecIdentityAPI:
    """Read the caller's own identity and recorded session subject."""

    _request: Callable[..., Awaitable[httpx.Response]]

    async def whoami(self) -> WhoAmIDTO:
        """Read the caller's own session facts from the daemon."""
        response = await self._request(HTTPMethod.GET, _AUTH_WHOAMI_ROUTE)
        return WhoAmIDTO.model_validate_json(response.text)

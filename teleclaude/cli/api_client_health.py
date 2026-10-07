"""Liveness query surface for the TeleClaude API client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPMethod

import httpx

from teleclaude.api_models_health import HealthDTO

_HEALTH_ROUTE = "/health"


class TelecHealthAPI:
    """Read the daemon's liveness and the commit it started from."""

    _request: Callable[..., Awaitable[httpx.Response]]

    async def get_health(self) -> HealthDTO:
        """Read the daemon's liveness and the commit its code stood on at its start."""
        response = await self._request(HTTPMethod.GET, _HEALTH_ROUTE)
        return HealthDTO.model_validate_json(response.text)

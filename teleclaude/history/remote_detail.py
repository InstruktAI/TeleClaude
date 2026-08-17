"""Direct remote mirror detail client retained outside federated search."""

from __future__ import annotations

import httpx

from teleclaude.cli.api_client import TelecAPIClient

_REMOTE_API_PORT = 8420
_REMOTE_API_BASE_TEMPLATE = "http://{host}:{port}"


async def resolve_remote_detail_base(computer: str) -> str:
    """Resolve one remote host through the authenticated local daemon client."""
    client = TelecAPIClient()
    await client.connect()
    try:
        computers = await client.list_computers()
    finally:
        await client.close()
    for candidate in computers:
        if candidate.name == computer:
            host = candidate.host or computer
            return _REMOTE_API_BASE_TEMPLATE.format(host=host, port=_REMOTE_API_PORT)
    raise LookupError(f"Computer '{computer}' not found in local daemon cache")


async def get_remote_detail(base_url: str, path: str) -> httpx.Response:
    """Fetch one mirror detail or raw transcript from its current direct route."""
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response

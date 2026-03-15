"""Characterization tests for teleclaude.hooks.api_routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from teleclaude.hooks import api_routes
from teleclaude.hooks.webhook_models import Contract


@dataclass
class _RegistryStub:
    list_contracts_impl: Callable[[str | None, str | None], Awaitable[list[Contract]]] | None = None
    list_properties_impl: Callable[[], Awaitable[dict[str, set[str]]]] | None = None
    deactivate_result: bool = True
    registered: list[Contract] | None = None

    async def list_contracts(
        self, property_name: str | None = None, property_value: str | None = None
    ) -> list[Contract]:
        if self.list_contracts_impl is None:
            return []
        return await self.list_contracts_impl(property_name, property_value)

    async def register(self, contract: Contract) -> None:
        if self.registered is None:
            self.registered = []
        self.registered.append(contract)

    async def deactivate(self, _contract_id: str) -> bool:
        return self.deactivate_result

    async def list_properties(self) -> dict[str, set[str]]:
        if self.list_properties_impl is None:
            return {}
        return await self.list_properties_impl()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_routes.router)
    return app


class TestApiRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_contract_registers_url_target_and_redacts_secret(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        registry = _RegistryStub(registered=[])
        monkeypatch.setattr(api_routes, "_contract_registry", registry)

        transport = httpx.ASGITransport(app=_build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/hooks/contracts",
                json={
                    "id": "contract-1",
                    "target": {"url": "https://example.test/hook", "secret": "top-secret"},
                    "source_criterion": {"match": "github"},
                    "properties": {"repo": {"match": "owner/repo"}},
                    "ttl_seconds": 60,
                },
            )

        body = response.json()

        assert response.status_code == 201
        assert body["id"] == "contract-1"
        assert body["target"] == {
            "handler": None,
            "url": "https://example.test/hook",
            "secret": None,
        }
        assert body["source"] == "api"
        assert body["expires_at"] is not None
        assert registry.registered is not None
        assert len(registry.registered) == 1
        assert registry.registered[0].target.secret == "top-secret"
        assert registry.registered[0].properties["repo"].match == "owner/repo"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_contract_rejects_requests_that_set_both_handler_and_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(api_routes, "_contract_registry", _RegistryStub())

        transport = httpx.ASGITransport(app=_build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/hooks/contracts",
                json={
                    "id": "contract-2",
                    "target": {"handler": "internal", "url": "https://example.test/hook"},
                },
            )

        assert response.status_code == 422

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_properties_sorts_values_returned_by_the_registry(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _list_properties() -> dict[str, set[str]]:
            return {"repo": {"zeta", "alpha"}, "source": {"github"}}

        monkeypatch.setattr(api_routes, "_contract_registry", _RegistryStub(list_properties_impl=_list_properties))

        transport = httpx.ASGITransport(app=_build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/hooks/properties")

        assert response.status_code == 200
        assert response.json() == {"repo": ["alpha", "zeta"], "source": ["github"]}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_contract_routes_return_service_unavailable_when_registry_is_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(api_routes, "_contract_registry", None)

        transport = httpx.ASGITransport(app=_build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/hooks/contracts")

        assert response.status_code == 503

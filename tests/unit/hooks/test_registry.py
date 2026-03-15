"""Characterization tests for teleclaude.hooks.registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.hooks.registry as registry_module
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion, Target


@dataclass
class _DbStub:
    list_webhook_contracts: AsyncMock
    upsert_webhook_contract: AsyncMock
    deactivate_webhook_contract: AsyncMock


def _make_contract(contract_id: str, **kwargs: object) -> Contract:
    kwargs.setdefault("target", Target(handler="handler"))
    return Contract(id=contract_id, **kwargs)


class TestContractRegistry:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_load_from_db_keeps_only_rows_that_deserialize_into_contracts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        valid = _make_contract("contract-1")
        db_stub = _DbStub(
            list_webhook_contracts=AsyncMock(
                return_value=[
                    SimpleNamespace(id="contract-1", contract_json=valid.to_json()),
                    SimpleNamespace(id="broken", contract_json="{"),
                ]
            ),
            upsert_webhook_contract=AsyncMock(),
            deactivate_webhook_contract=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(registry_module, "db", db_stub)

        registry = ContractRegistry()
        await registry.load_from_db()

        assert [contract.id for contract in await registry.list_contracts()] == ["contract-1"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_persists_json_and_makes_contract_matchable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        contract = _make_contract("contract-2", target=Target(url="https://example.test/hook"))
        db_stub = _DbStub(
            list_webhook_contracts=AsyncMock(return_value=[]),
            upsert_webhook_contract=AsyncMock(),
            deactivate_webhook_contract=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(registry_module, "db", db_stub)
        monkeypatch.setattr(registry_module, "match_event", lambda event, current: current.id == "contract-2")

        registry = ContractRegistry()
        await registry.register(contract)
        matches = registry.match(
            HookEvent(
                source="github",
                type="pull_request",
                timestamp="2025-01-01T00:00:00+00:00",
            )
        )

        db_stub.upsert_webhook_contract.assert_awaited_once_with("contract-2", contract.to_json(), "api")
        assert [matched.id for matched in matches] == ["contract-2"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_contracts_filters_properties_and_source_type_criteria(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_stub = _DbStub(
            list_webhook_contracts=AsyncMock(return_value=[]),
            upsert_webhook_contract=AsyncMock(),
            deactivate_webhook_contract=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(registry_module, "db", db_stub)

        repo_contract = _make_contract(
            "contract-3",
            properties={"repo": PropertyCriterion(match=["owner/repo", "owner/docs"])},
        )
        source_contract = _make_contract(
            "contract-4",
            source_criterion=PropertyCriterion(match="github"),
            type_criterion=PropertyCriterion(match="pull_request"),
        )
        registry = ContractRegistry()
        await registry.register(repo_contract)
        await registry.register(source_contract)

        repo_matches = await registry.list_contracts(property_name="repo", property_value="owner/docs")
        source_matches = await registry.list_contracts(property_name="source", property_value="github")
        type_matches = await registry.list_contracts(property_name="type", property_value="pull_request")

        assert [contract.id for contract in repo_matches] == ["contract-3"]
        assert [contract.id for contract in source_matches] == ["contract-4"]
        assert [contract.id for contract in type_matches] == ["contract-4"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_properties_includes_expired_active_contracts_but_skips_inactive_contracts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_stub = _DbStub(
            list_webhook_contracts=AsyncMock(return_value=[]),
            upsert_webhook_contract=AsyncMock(),
            deactivate_webhook_contract=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(registry_module, "db", db_stub)

        expired = _make_contract(
            "expired",
            source_criterion=PropertyCriterion(match="github"),
            properties={"repo": PropertyCriterion(match="owner/repo")},
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
        inactive = _make_contract(
            "inactive",
            active=False,
            properties={"repo": PropertyCriterion(match="owner/ignored")},
        )
        registry = ContractRegistry()
        await registry.register(expired)
        await registry.register(inactive)

        assert registry.list_properties() == {
            "source": {"github"},
            "repo": {"owner/repo"},
        }

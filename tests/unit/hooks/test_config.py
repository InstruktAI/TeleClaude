"""Characterization tests for teleclaude.hooks.config."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from teleclaude.core.models import JsonDict
from teleclaude.hooks.config import load_hooks_config, parse_criterion
from teleclaude.hooks.webhook_models import Contract


@dataclass
class _ContractRegistryStub:
    registered: list[Contract] = field(default_factory=list)

    async def register(self, contract: Contract) -> None:
        self.registered.append(contract)


@dataclass
class _InboundRegistryStub:
    registered: list[tuple[str, str, JsonDict | None]] = field(default_factory=list)

    def register(self, path: str, normalizer_key: str, verify_config: JsonDict | None = None) -> None:
        self.registered.append((path, normalizer_key, verify_config))


class TestParseCriterion:
    @pytest.mark.unit
    def test_required_defaults_true_when_not_present(self) -> None:
        criterion = parse_criterion({"match": "github"})

        assert criterion.match == "github"
        assert criterion.pattern is None
        assert criterion.required is True


class TestLoadHooksConfig:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_loads_contract_criteria_and_derives_inbound_path_from_source_name(self) -> None:
        contract_registry = _ContractRegistryStub()
        inbound_registry = _InboundRegistryStub()

        await load_hooks_config(
            {
                "subscriptions": [
                    {
                        "id": "contract-1",
                        "contract": {
                            "source": {"match": "github"},
                            "type": {"pattern": "pull_*"},
                            "repo": {"match": "owner/repo", "required": False},
                        },
                        "target": {"handler": "dispatch-github"},
                    }
                ],
                "inbound": {
                    "github": {
                        "verify_token": "verify-me",
                        "secret": "signing-secret",
                    }
                },
            },
            contract_registry,
            inbound_registry,
        )

        assert len(contract_registry.registered) == 1
        contract = contract_registry.registered[0]
        assert contract.id == "contract-1"
        assert contract.target.handler == "dispatch-github"
        assert contract.source == "config"
        assert contract.source_criterion is not None
        assert contract.source_criterion.match == "github"
        assert contract.type_criterion is not None
        assert contract.type_criterion.pattern == "pull_*"
        assert contract.properties["repo"].required is False
        assert inbound_registry.registered == [
            (
                "/hooks/inbound/github",
                "github",
                {"verify_token": "verify-me", "secret": "signing-secret"},
            )
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_continues_loading_after_a_subscription_raises_during_contract_build(self) -> None:
        contract_registry = _ContractRegistryStub()

        await load_hooks_config(
            {
                "subscriptions": [
                    {
                        "contract": {"source": {"match": "github"}},
                        "target": {"handler": "missing-id"},
                    },
                    {
                        "id": "contract-2",
                        "contract": {"source": {"match": "whatsapp"}},
                        "target": {"url": "https://example.test/inbound"},
                    },
                ]
            },
            contract_registry,
        )

        assert [contract.id for contract in contract_registry.registered] == ["contract-2"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_uses_explicit_inbound_path_and_normalizer_override_when_present(self) -> None:
        contract_registry = _ContractRegistryStub()
        inbound_registry = _InboundRegistryStub()

        await load_hooks_config(
            {
                "inbound": {
                    "whatsapp": {
                        "path": "/webhooks/wa",
                        "normalizer": "meta-whatsapp",
                    }
                }
            },
            contract_registry,
            inbound_registry,
        )

        assert contract_registry.registered == []
        assert inbound_registry.registered == [("/webhooks/wa", "meta-whatsapp", None)]

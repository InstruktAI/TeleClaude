"""Contract registry — DB-backed storage with in-memory cache."""

from __future__ import annotations

import json

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.hooks.matcher import match_event
from teleclaude.hooks.webhook_models import Contract, HookEvent

logger = get_logger(__name__)


def _criterion_matches_property_value(match_val: str | list[str] | None, property_value: str | None) -> bool:
    """Return True when a criterion match value satisfies the property filter."""
    if property_value is None:
        return True
    if isinstance(match_val, list):
        return property_value in match_val
    return match_val == property_value


def _contract_matches_property_filter(
    contract: Contract,
    property_name: str,
    property_value: str | None,
) -> bool:
    """Return True when a contract matches the requested property filter."""
    if property_name in contract.properties:
        return _criterion_matches_property_value(contract.properties[property_name].match, property_value)
    if property_name == "source" and contract.source_criterion:
        return _criterion_matches_property_value(contract.source_criterion.match, property_value)
    if property_name == "type" and contract.type_criterion:
        return _criterion_matches_property_value(contract.type_criterion.match, property_value)
    return False


def _add_match_values(vocab: dict[str, set[str]], property_name: str, match_val: str | list[str] | None) -> None:
    """Merge a criterion's match values into the shared property vocabulary."""
    bucket = vocab.setdefault(property_name, set())
    if isinstance(match_val, str):
        bucket.add(match_val)
    elif match_val:
        bucket.update(match_val)


class ContractRegistry:
    """Manages webhook contracts with DB persistence and in-memory cache."""

    def __init__(self) -> None:
        self._cache: dict[str, Contract] = {}

    async def load_from_db(self) -> None:
        """Load all active contracts from DB into cache."""
        rows = await db.list_webhook_contracts(active_only=True)
        new_cache: dict[str, Contract] = {}
        for row in rows:
            try:
                contract = Contract.from_json(row.contract_json)
                new_cache[contract.id] = contract
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.error("Failed to load contract %s: %s", row.id, exc, exc_info=True)
        self._cache = new_cache
        logger.info("Loaded %d active contracts from DB", len(self._cache))

    async def register(self, contract: Contract) -> None:
        """Register or update a contract (DB + cache)."""
        await db.upsert_webhook_contract(contract.id, contract.to_json(), contract.source)
        self._cache[contract.id] = contract
        logger.debug("Registered contract: %s", contract.id)

    async def deactivate(self, contract_id: str) -> bool:
        """Deactivate a contract."""
        result = await db.deactivate_webhook_contract(contract_id)
        self._cache.pop(contract_id, None)
        return result

    def match(self, event: HookEvent) -> list[Contract]:
        """Find all active, non-expired contracts matching an event."""
        return [c for c in self._cache.values() if c.active and not c.is_expired and match_event(event, c)]

    async def sweep_expired(self) -> int:
        """Deactivate expired contracts. Returns count of swept contracts."""
        swept = 0
        for contract in list(self._cache.values()):
            if contract.active and contract.is_expired:
                await self.deactivate(contract.id)
                swept += 1
        if swept:
            logger.info("Swept %d expired contracts", swept)
        return swept

    async def list_contracts(
        self, property_name: str | None = None, property_value: str | None = None
    ) -> list[Contract]:
        """List active contracts, optionally filtered by property interest."""
        contracts = [c for c in self._cache.values() if c.active and not c.is_expired]
        if property_name:
            return [
                contract
                for contract in contracts
                if _contract_matches_property_filter(contract, property_name, property_value)
            ]
        return contracts

    def list_properties(self) -> dict[str, set[str]]:
        """Return union of all declared property names and their match values."""
        vocab: dict[str, set[str]] = {}
        for contract in self._cache.values():
            if not contract.active:
                continue
            if contract.source_criterion:
                _add_match_values(vocab, "source", contract.source_criterion.match)
            if contract.type_criterion:
                _add_match_values(vocab, "type", contract.type_criterion.match)
            for prop_name, criterion in contract.properties.items():
                _add_match_values(vocab, prop_name, criterion.match)
        return vocab

"""Contract registry — DB-backed storage with in-memory cache."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.hooks.matcher import match_event
from teleclaude.hooks.webhook_models import Contract, HookEvent

logger = get_logger(__name__)


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
            except Exception as exc:
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
            filtered = []
            for c in contracts:
                if property_name in c.properties:
                    if property_value is None:
                        filtered.append(c)
                    else:
                        match_val = c.properties[property_name].match
                        if match_val == property_value or (isinstance(match_val, list) and property_value in match_val):
                            filtered.append(c)
                # Also check source_criterion and type_criterion
                if property_name == "source" and c.source_criterion:
                    if property_value is None or c.source_criterion.match == property_value:
                        if c not in filtered:
                            filtered.append(c)
                if property_name == "type" and c.type_criterion:
                    if property_value is None or c.type_criterion.match == property_value:
                        if c not in filtered:
                            filtered.append(c)
            return filtered
        return contracts

    def list_properties(self) -> dict[str, set[str]]:
        """Return union of all declared property names and their match values."""
        vocab: dict[str, set[str]] = {}
        for contract in self._cache.values():
            if not contract.active:
                continue
            # Add source criterion
            if contract.source_criterion and contract.source_criterion.match:
                match_val = contract.source_criterion.match
                if isinstance(match_val, str):
                    vocab.setdefault("source", set()).add(match_val)
                else:
                    vocab.setdefault("source", set()).update(match_val)
            # Add type criterion
            if contract.type_criterion and contract.type_criterion.match:
                match_val = contract.type_criterion.match
                if isinstance(match_val, str):
                    vocab.setdefault("type", set()).add(match_val)
                else:
                    vocab.setdefault("type", set()).update(match_val)
            # Add property criteria
            for prop_name, criterion in contract.properties.items():
                if criterion.match:
                    match_val = criterion.match
                    if isinstance(match_val, str):
                        vocab.setdefault(prop_name, set()).add(match_val)
                    else:
                        vocab.setdefault(prop_name, set()).update(match_val)
                else:
                    vocab.setdefault(prop_name, set())
        return vocab

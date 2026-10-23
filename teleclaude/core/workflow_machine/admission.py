"""Neutral, one-time item facts carried from workflow admission to session creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from teleclaude.core.workflow_store.types import ItemIdentity, StoreAddress

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore


@dataclass(frozen=True, kw_only=True)
class DriverAdmission:
    """The store-owned item identity a driver start was admitted for."""

    item: ItemIdentity


@dataclass(frozen=True, kw_only=True)
class ChildAdmission(DriverAdmission):
    """A child start admitted for its qualified holding parent."""

    parent_computer: str
    parent_session_id: str


async def admitted_identity(store: WorkflowStore, item: str) -> ItemIdentity | None:
    """Read the selected store's canonical identity from the address it resolves for this item."""
    address = store.resolve_store_address_sync(item)
    if not address:
        return None
    identity = await store.resolve_live_slug_by_id(address)
    if not identity.slug:
        return None
    return ItemIdentity(identity.slug, StoreAddress(address))

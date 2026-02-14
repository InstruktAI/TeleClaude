"""FastAPI router for webhook contract management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from teleclaude.hooks.registry import ContractRegistry  # type: ignore[import-not-found]  # Track B dependency
    from teleclaude.hooks.webhook_models import Contract

router = APIRouter(prefix="/hooks", tags=["hooks"])

# Lazy reference — set by daemon during startup
_contract_registry: ContractRegistry | None = None


def set_contract_registry(registry: ContractRegistry) -> None:
    """Called by daemon to inject the ContractRegistry instance."""
    global _contract_registry
    _contract_registry = registry


def _get_registry() -> ContractRegistry:
    if _contract_registry is None:
        raise HTTPException(status_code=503, detail="Webhook service not initialized")
    return _contract_registry


class CreateContractRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    target: dict[str, str | None]
    source_criterion: dict[str, Any] | None = None  # guard: loose-dict - Pydantic request DTO accepts arbitrary JSON
    type_criterion: dict[str, Any] | None = None  # guard: loose-dict - Pydantic request DTO accepts arbitrary JSON
    properties: dict[str, dict[str, Any]] = {}  # guard: loose-dict - Pydantic request DTO accepts arbitrary JSON


class ContractResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source_criterion: dict[str, Any] | None = None  # guard: loose-dict - Pydantic response DTO
    type_criterion: dict[str, Any] | None = None  # guard: loose-dict - Pydantic response DTO
    properties: dict[str, dict[str, Any]] = {}  # guard: loose-dict - Pydantic response DTO
    target: dict[str, str | None] = {}  # guard: loose-dict - Pydantic response DTO
    active: bool = True
    created_at: str = ""
    source: str = "api"


def _contract_to_response(contract: Contract) -> ContractResponse:
    """Convert a Contract to a response DTO."""
    from dataclasses import asdict

    return ContractResponse(
        id=contract.id,
        source_criterion=asdict(contract.source_criterion) if contract.source_criterion else None,
        type_criterion=asdict(contract.type_criterion) if contract.type_criterion else None,
        properties={k: asdict(v) for k, v in contract.properties.items()},
        target={"handler": contract.target.handler, "url": contract.target.url, "secret": contract.target.secret},
        active=contract.active,
        created_at=contract.created_at,
        source=contract.source,
    )


@router.get("/contracts")
async def list_contracts(
    property: str | None = Query(default=None, description="Filter by property name"),
    value: str | None = Query(default=None, description="Filter by property value"),
) -> list[ContractResponse]:
    """List all active contracts, optionally filtered by property."""
    registry = _get_registry()
    contracts = await registry.list_contracts(property_name=property, property_value=value)
    return [_contract_to_response(c) for c in contracts]


@router.get("/properties")
async def list_properties() -> dict[str, list[str]]:
    """Union of all properties declared across all active contracts."""
    registry = _get_registry()
    vocab = registry.list_properties()
    return {k: sorted(v) for k, v in vocab.items()}


@router.post("/contracts", status_code=201)
async def create_contract(req: CreateContractRequest) -> ContractResponse:
    """Create a new webhook contract."""
    from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target

    target = Target(
        handler=req.target.get("handler"),
        url=req.target.get("url"),
        secret=req.target.get("secret"),
    )
    source_criterion = PropertyCriterion(**req.source_criterion) if req.source_criterion else None
    type_criterion = PropertyCriterion(**req.type_criterion) if req.type_criterion else None
    properties = {k: PropertyCriterion(**v) for k, v in req.properties.items()}

    contract = Contract(
        id=req.id,
        target=target,
        source_criterion=source_criterion,
        type_criterion=type_criterion,
        properties=properties,
        source="api",
    )

    registry = _get_registry()
    await registry.register(contract)
    return _contract_to_response(contract)


@router.delete("/contracts/{contract_id}")
async def deactivate_contract(contract_id: str) -> dict[str, str]:
    """Deactivate a contract."""
    registry = _get_registry()
    found = await registry.deactivate(contract_id)
    if not found:
        raise HTTPException(status_code=404, detail="Contract not found")
    return {"deactivated": contract_id}

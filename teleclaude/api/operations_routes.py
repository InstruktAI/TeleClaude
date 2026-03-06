"""FastAPI routes for durable long-running operation receipts."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from teleclaude.api.auth import CLEARANCE_OPERATIONS_GET, CallerIdentity
from teleclaude.api_models import OperationStatusDTO, OperationStatusPayload
from teleclaude.core.operations import get_operations_service

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/{operation_id}", response_model=OperationStatusDTO, response_model_exclude_none=True)
async def get_operation(
    operation_id: str,
    identity: CallerIdentity = Depends(CLEARANCE_OPERATIONS_GET),
) -> OperationStatusPayload:
    """Fetch receipt-backed operation status for the caller."""
    operations = get_operations_service()
    return await operations.get_operation_for_caller(
        operation_id=operation_id,
        caller_session_id=identity.session_id,
        human_role=identity.human_role,
    )

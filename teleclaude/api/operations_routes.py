"""FastAPI routes for durable long-running operation receipts."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, carried_caller
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.core.operations.service import SerializedOperation, get_operations_service

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/{operation_id}", response_model=OperationStatusDTO, response_model_exclude_none=True)
async def get_operation(
    operation_id: str,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Fetch receipt-backed operation status for the caller; one on another computer is read there."""
    operations = get_operations_service()
    return await operations.get_operation_for_caller(
        operation_id=operation_id,
        caller_session_id=identity.session_id,
        caller=caller_for_role_resolution(identity),
    )

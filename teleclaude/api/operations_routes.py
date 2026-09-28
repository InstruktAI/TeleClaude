"""FastAPI routes for durable long-running operation receipts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.api.session_remote import is_remote_target
from teleclaude.api.session_route_helpers import http_exception_for_relay_failure
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.config import config
from teleclaude.core.command_dispatch import RelayFailure, relay_caller_read
from teleclaude.core.models import JsonDict
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

router = APIRouter(prefix="/operations", tags=["operations"])

_STATE = SimpleNamespace(client=None)
_OPERATION_ID_FIELD = "operation_id"
_GET_OPERATION_COMMAND = "get_operation"


def configure(client: AdapterClient | None = None) -> None:
    """Wire the transport client; called from APIServer at construction."""
    if client is not None:
        _STATE.client = client


@router.get("/{operation_id}", response_model=OperationStatusDTO, response_model_exclude_none=True)
async def get_operation(
    operation_id: str,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Fetch receipt-backed operation status for the caller, local or on a named owning computer."""
    if is_remote_target(computer, config.computer.name):
        if _STATE.client is None:
            raise HTTPException(status_code=503, detail="Remote operation read is unavailable")
        principal = principal_for_carried_caller(identity, required=True)
        target_computer = computer or ""
        request: JsonDict = {_OPERATION_ID_FIELD: operation_id}
        try:
            data = await relay_caller_read(
                _STATE.client,
                target_computer,
                _GET_OPERATION_COMMAND,
                principal=principal,
                request=request,
            )
        except RelayFailure as exc:
            raise http_exception_for_relay_failure(exc) from exc
        return cast(SerializedOperation, data)

    operations = get_operations_service()
    return await operations.get_operation_for_caller(
        operation_id=operation_id,
        caller_session_id=identity.session_id,
        caller=caller_for_role_resolution(identity),
    )

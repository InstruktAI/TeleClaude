"""FastAPI routes for durable long-running operation receipts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    caller_role_at_platform,
    carried_caller,
)
from teleclaude.api.session_remote import is_remote_target
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.config import config
from teleclaude.core.command_dispatch import parse_remote_dispatch_data_diagnosed
from teleclaude.core.models import MessageMetadata
from teleclaude.core.models._types import SessionOriginMetadata
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

router = APIRouter(prefix="/operations", tags=["operations"])

_STATE = SimpleNamespace(client=None)


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
        target_computer = computer or ""
        metadata = MessageMetadata(
            origin_metadata=cast(SessionOriginMetadata, {"operation_id": operation_id}),
            human_role=caller_role_at_platform(identity),
        )
        message_id = await _STATE.client.send_request(
            target_computer,
            "get_operation",
            metadata,
            session_id=identity.session_id,
        )
        response_text = await _STATE.client.read_response(message_id, target_computer=target_computer)
        data = await parse_remote_dispatch_data_diagnosed(
            _STATE.client,
            response_text,
            target_computer=target_computer,
            command="get_operation",
        )
        return cast(SerializedOperation, data)

    operations = get_operations_service()
    return await operations.get_operation_for_caller(
        operation_id=operation_id,
        caller_session_id=identity.session_id,
        caller=caller_for_role_resolution(identity),
    )

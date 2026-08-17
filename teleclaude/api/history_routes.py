"""Authenticated local and federated history search route."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import TypeAdapter

from teleclaude.api.auth import CallerIdentity, clearance_history_search
from teleclaude.api.session_remote import is_remote_target
from teleclaude.config import config
from teleclaude.core.command_dispatch import parse_remote_dispatch_data_diagnosed
from teleclaude.core.models import JsonDict, MessageMetadata
from teleclaude.history.service import (
    HistorySearchPayload,
    build_history_search_payload,
    parse_history_agents,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

REMOTE_HISTORY_SEARCH_COMMAND = "history_search"
_NO_REMOTE_COMPUTER = ""

_STATE = SimpleNamespace(client=None)
router = APIRouter()


def configure(client: AdapterClient | None = None) -> None:
    """Wire the peer transport used for federated search."""
    if client is not None:
        _STATE.client = client


@router.get("/history/search")
async def search_history(
    q: str = "",
    agent: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    computer: str | None = None,
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
    caller: CallerIdentity = Depends(clearance_history_search),
) -> HistorySearchPayload:
    """Search local or peer mirrors through the authenticated daemon boundary."""
    try:
        agents = parse_history_agents(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown agent filter: {agent}") from exc

    if is_remote_target(computer, config.computer.name):
        if _STATE.client is None:
            raise HTTPException(status_code=503, detail="Remote history search is unavailable")
        target_computer = computer or _NO_REMOTE_COMPUTER
        origin_metadata = cast(
            JsonDict,
            {
                "q": q,
                "agent": agent,
                "limit": limit,
                "include_workers": include_workers,
                "identity": identity,
                "project": project,
            },
        )
        metadata = MessageMetadata(
            origin_metadata=origin_metadata,
            human_email=caller.email,
            human_role=caller.human_role,
        )
        message_id = await _STATE.client.send_request(
            target_computer,
            REMOTE_HISTORY_SEARCH_COMMAND,
            metadata,
        )
        response_text = await _STATE.client.read_response(
            message_id,
            target_computer=target_computer,
        )
        data = await parse_remote_dispatch_data_diagnosed(
            _STATE.client,
            response_text,
            target_computer=target_computer,
            command=REMOTE_HISTORY_SEARCH_COMMAND,
        )
        return TypeAdapter(HistorySearchPayload).validate_python(data)

    return await asyncio.to_thread(
        build_history_search_payload,
        computer=config.computer.name,
        query=q,
        agents=agents,
        limit=limit,
        caller_email=caller.email,
        caller_role=caller.human_role,
        include_workers=include_workers,
        identity=identity,
        project=project,
    )

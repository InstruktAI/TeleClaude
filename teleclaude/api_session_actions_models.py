"""Typed request and response bodies for session action endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from teleclaude.agent_registry import AgentName
from teleclaude.api_models_operations import OperationStatusDTO


class AgentRestartRequest(BaseModel):
    """Optional intent carried by the restart endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    self_restart: bool = False
    handoff: bool = False
    agent: AgentName | None = None


class AgentRestartResponseDTO(OperationStatusDTO):
    """Restart/handoff receipt; selection rides the receipt for the handoff branch."""

    selected_agent: AgentName | None = None

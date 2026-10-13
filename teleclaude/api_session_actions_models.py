"""Typed request and response bodies for session action endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class RunPersonalAssistantRequest(BaseModel):
    """Optional-brief request to launch the caller's personal assistant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brief: str | None = Field(default=None, min_length=1)


class SendResultRequest(BaseModel):
    """Request to send a formatted result to the session's user (POST /sessions/self/result)."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(..., min_length=1)
    output_format: Literal["markdown", "html"] = "markdown"


class EscalateRequest(BaseModel):
    """Request to escalate a customer session to Discord (POST /sessions/self/escalate)."""

    model_config = ConfigDict(frozen=True)

    customer_name: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    context_summary: str | None = None

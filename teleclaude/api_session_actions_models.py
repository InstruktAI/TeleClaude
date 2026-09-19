"""Typed request and response bodies for session action endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from teleclaude.agent_registry import AgentName


class AgentRestartRequest(BaseModel):
    """Optional intent carried by the restart endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    self_restart: bool = False
    handoff: bool = False
    agent: AgentName | None = None


class AgentRestartResponseDTO(BaseModel):
    """Immediate acceptance or selection result for an agent restart."""

    model_config = ConfigDict(frozen=True)

    status: Literal["accepted"]
    completion_event: str
    selected_agent: AgentName | None = None


class HumanInvolvementValidationRequest(BaseModel):
    """Ephemeral declaration submitted for one fact-producing action."""

    model_config = ConfigDict(frozen=True)

    reason: str | None = None


class HumanInvolvementValidationResponseDTO(BaseModel):
    """Reason-safe result of self-scoped involvement validation."""

    model_config = ConfigDict(frozen=True)

    human_involved: bool
    refusal: str | None = None
    latest_human_input_age_seconds: int | None = None

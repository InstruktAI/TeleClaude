"""API request/response models for REST adapter."""

from typing import Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to create a new session."""

    computer: str = Field(..., min_length=2)
    project_dir: str = Field(..., min_length=2)
    agent: Literal["claude", "gemini", "codex"] = "claude"
    thinking_mode: Literal["fast", "med", "slow"] = "slow"
    title: str | None = None
    message: str | None = None
    auto_command: str | None = None


class SendMessageRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a message to a session."""

    message: str = Field(..., min_length=1)

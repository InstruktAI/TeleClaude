"""API request/response models for REST adapter."""

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to create a new session."""

    computer: str
    project_dir: str
    agent: str = "claude"
    thinking_mode: str = "slow"
    title: str | None = None
    message: str | None = None


class SendMessageRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a message to a session."""

    message: str

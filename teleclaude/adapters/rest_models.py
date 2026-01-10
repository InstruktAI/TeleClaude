"""API request/response models for REST adapter."""

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    computer: str
    project_dir: str
    agent: str = "claude"
    thinking_mode: str = "slow"
    title: str | None = None
    message: str | None = None


class SendMessageRequest(BaseModel):
    """Request to send a message to a session."""

    message: str


class SessionResponse(BaseModel):
    """Session information response."""

    session_id: str
    computer: str
    title: str | None
    tmux_session_name: str
    active_agent: str | None
    thinking_mode: str | None
    last_activity: str
    last_input: str | None  # Maps to last_message_sent
    last_output: str | None  # Maps to last_feedback_received
    initiator_session_id: str | None  # For AI-to-AI nesting
    working_directory: str | None


class ComputerResponse(BaseModel):
    """Computer information response."""

    name: str
    status: str  # "online" only (offline filtered out)
    user: str | None
    host: str | None


class ProjectResponse(BaseModel):
    """Project information response."""

    computer: str
    name: str
    path: str
    description: str | None


class AgentAvailability(BaseModel):
    """Agent availability status."""

    agent: str
    available: bool
    unavailable_until: str | None
    reason: str | None


class TodoResponse(BaseModel):
    """Todo item from roadmap.md."""

    slug: str
    status: str  # "pending", "ready", "in_progress"
    description: str | None
    has_requirements: bool
    has_impl_plan: bool

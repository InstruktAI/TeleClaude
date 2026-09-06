"""API response shape for explicit live terminal observations."""

from pydantic import BaseModel, ConfigDict


class SessionPaneDTO(BaseModel):
    """Response for GET /sessions/{session_id}/pane."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    runtime: str | None = None
    captured_at: str
    available: bool
    text: str

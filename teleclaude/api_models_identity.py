"""Identity API DTOs with no config or storage dependencies."""

from pydantic import BaseModel, ConfigDict


class WhoAmIDTO(BaseModel):
    """Resolved caller identity returned by the daemon."""

    model_config = ConfigDict(frozen=True)

    principal: str | None = None
    role: str | None = None
    email: str | None = None
    session_id: str | None = None
    config_subject: str | None = None

"""Liveness API DTOs with no config or storage dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthDTO(BaseModel):
    """Liveness of the daemon, and the commit its code checkout stood on when it started."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    start_commit: str | None = None

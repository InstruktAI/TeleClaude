"""Typed session attachment inputs resolved for the serving daemon."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionAttachmentDestinationKind(StrEnum):
    """Closed set of resolved destinations for a session viewer."""

    LOCAL = "local"
    SSH = "ssh"


class LocalSessionAttachmentDTO(BaseModel):
    """A session host reached through the serving daemon's local tmux."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[SessionAttachmentDestinationKind.LOCAL] = SessionAttachmentDestinationKind.LOCAL


class SshSessionAttachmentDTO(BaseModel):
    """Connection inputs for a session host reached through SSH."""

    model_config = ConfigDict(frozen=True)

    kind: Literal[SessionAttachmentDestinationKind.SSH] = SessionAttachmentDestinationKind.SSH
    user: str
    host: str


type SessionAttachmentDestinationDTO = Annotated[
    LocalSessionAttachmentDTO | SshSessionAttachmentDTO,
    Field(discriminator="kind"),
]

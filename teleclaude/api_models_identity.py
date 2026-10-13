"""Identity API DTOs with no config or storage dependencies."""

from pydantic import BaseModel, ConfigDict, Field


class WhoAmIDTO(BaseModel):
    """Resolved caller identity returned by the daemon."""

    model_config = ConfigDict(frozen=True)

    principal: str | None = None
    role: str | None = None
    email: str | None = None
    session_id: str | None = None
    config_subject: str | None = None
    person_slug: str | None = None


class ChipColorPairDTO(BaseModel):
    """A theme-split chip color: one value for light mode, one for dark; unset cells use the client's defaults."""

    model_config = ConfigDict(frozen=True)

    light: str | None = None
    dark: str | None = None


class PersonChipDTO(BaseModel):
    """Display facts of the person a row belongs to: uppercase initials and per-theme chip colors."""

    model_config = ConfigDict(frozen=True)

    initials: str
    background: ChipColorPairDTO = Field(default_factory=ChipColorPairDTO)
    text: ChipColorPairDTO = Field(default_factory=ChipColorPairDTO)


class OwnershipSurfaceDTO(BaseModel):
    """Whether owner chips and the per-person filter apply: only when more than one person is registered."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False

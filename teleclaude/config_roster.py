"""Lightweight access to the people roster used for caller identity."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.paths import GLOBAL_CONFIG_PATH
from teleclaude.slug import validate_slug

ProficiencyLevel = Literal["novice", "intermediate", "advanced", "expert"]


class PersonEntry(ClosedModel):
    """Person identity and role configuration."""

    name: str
    email: str = Field(min_length=1)
    slug: str | None = None
    username: str | None = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"
    preferences: str | None = None
    expertise: dict[str, ProficiencyLevel] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize and reject empty person email values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Person email must be non-empty")
        return normalized

    @field_validator("slug")
    @classmethod
    def validate_person_slug(cls, value: str | None) -> str | None:
        """Normalize optional slugs and validate non-empty values."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        validate_slug(normalized)
        return normalized


def load_people_roster(path: Path | None = None) -> list[PersonEntry]:
    """Read and validate only registered people, tolerating unrelated bad config."""
    source = GLOBAL_CONFIG_PATH if path is None else path
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return []
    if not isinstance(loaded, dict):
        return []
    people = loaded.get("people")
    if not isinstance(people, list):
        return []
    result: list[PersonEntry] = []
    for item in people:
        try:
            result.append(PersonEntry.model_validate(item))
        except ValidationError:
            continue
    return result

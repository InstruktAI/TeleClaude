"""Session response presentation helpers."""

from __future__ import annotations

from teleclaude.api_models import SessionDTO
from teleclaude.config.loader import load_global_config


def enrich_human_names(dtos: list[SessionDTO]) -> list[SessionDTO]:
    """Resolve human_name from people config for each DTO with a human_email."""
    people = load_global_config().people
    name_by_email = {person.email.lower(): person.name for person in people if person.email}
    return [
        dto.model_copy(update={"human_name": name_by_email[dto.human_email.lower()]})
        if dto.human_email and dto.human_email.lower() in name_by_email
        else dto
        for dto in dtos
    ]

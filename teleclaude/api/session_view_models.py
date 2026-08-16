"""Session response presentation helpers."""

from __future__ import annotations

from fastapi import Request

from teleclaude.api_models import SessionDTO
from teleclaude.config.loader import load_global_config
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER
from teleclaude.core.models import SessionSnapshot


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


def filter_sessions_by_role(request: Request, sessions: list[SessionSnapshot]) -> list[SessionSnapshot]:
    """Apply the web caller's session visibility envelope."""
    email = request.headers.get("x-web-user-email")
    role = request.headers.get("x-web-user-role")
    if not email or role == HUMAN_ROLE_ADMIN:
        return sessions
    if role == HUMAN_ROLE_MEMBER:
        return [session for session in sessions if session.human_email == email or session.visibility == "shared"]
    return [session for session in sessions if session.human_email == email]

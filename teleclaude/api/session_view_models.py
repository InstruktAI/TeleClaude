"""Session response presentation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from teleclaude.api.person_display import with_person_chips_on_sessions
from teleclaude.api_models import SessionDTO
from teleclaude.api_session_attachment import (
    LocalSessionAttachmentDTO,
    SessionAttachmentDestinationDTO,
    SshSessionAttachmentDTO,
)
from teleclaude.config.loader import load_global_config
from teleclaude.core.command_dispatch import is_remote_target
from teleclaude.core.session_status import project_host_pane_access

if TYPE_CHECKING:
    from teleclaude.core.models import ComputerInfo, SessionSnapshot


def _resolve_session_attachment_destination(
    session_computer: str | None,
    *,
    serving_computer: str,
    computer_registry: Mapping[str, ComputerInfo],
) -> SessionAttachmentDestinationDTO | None:
    """Resolve a session's connection inputs relative to the serving daemon."""
    if not session_computer:
        return None
    if not is_remote_target(session_computer, serving_computer):
        return LocalSessionAttachmentDTO()

    computer = computer_registry.get(session_computer)
    if computer is None or not computer.user or not computer.host:
        return None
    return SshSessionAttachmentDTO(user=computer.user, host=computer.host)


def project_session_dtos(
    sessions: Iterable[SessionSnapshot],
    *,
    serving_computer: str,
    computer_registry: Iterable[ComputerInfo],
) -> list[SessionDTO]:
    """Build the shared public session projection for HTTP and socket readers."""
    computers = {computer.name: computer for computer in computer_registry}
    dtos: list[SessionDTO] = []
    for session in sessions:
        access = project_host_pane_access(session)
        dto = SessionDTO.from_core(session, computer=session.computer)
        destination = _resolve_session_attachment_destination(
            session.computer,
            serving_computer=serving_computer,
            computer_registry=computers,
        )
        dtos.append(
            dto.model_copy(
                update={
                    "host_viewer_admission": access.viewer_admission,
                    "selection_disposition": access.selection,
                    "attachment_destination": destination,
                }
            )
        )
    return with_person_chips_on_sessions(_enrich_human_names(dtos))


def _enrich_human_names(dtos: list[SessionDTO]) -> list[SessionDTO]:
    """Resolve human_name from people config for each DTO with a human_email."""
    people = load_global_config().people
    name_by_email = {person.email.lower(): person.name for person in people if person.email}
    return [
        dto.model_copy(update={"human_name": name_by_email[dto.human_email.lower()]})
        if dto.human_email and dto.human_email.lower() in name_by_email
        else dto
        for dto in dtos
    ]

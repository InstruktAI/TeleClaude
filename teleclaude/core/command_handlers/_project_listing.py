"""Project listing command handler."""

from __future__ import annotations

from teleclaude.config.checkout_association import CheckoutPurpose
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.models._snapshot import ProjectInfo, ProjectLocationInfo
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.services.project_catalog import get_project_catalog_service


async def list_projects() -> list[ProjectInfo]:
    """List every present session-placement entry in registry order.

    Ephemeral request/response - no DB session required.

    Returns:
        List of project info objects.
    """
    catalog = get_project_catalog_service()
    catalog.refresh()
    return [
        ProjectInfo(
            name=entry.display_name,
            description=entry.description,
            path=str(entry.root),
            subject=(
                SubjectRef(ConfigSubjectKind(entry.kind.value), entry.identity).to_token()
                if entry.identity is not None
                else EventHomeMarker.UNKNOWN.value
            ),
            owner=entry.owner,
            locations=(
                [
                    ProjectLocationInfo(path=str(entry.root), purpose=CheckoutPurpose.INSTALLED),
                    ProjectLocationInfo(
                        path=str(entry.development_checkout),
                        purpose=CheckoutPurpose.DEVELOPMENT,
                    ),
                ]
                if entry.development_checkout is not None
                else []
            ),
        )
        for entry in catalog.list_entries()
    ]

"""Resolve caller identity into a history access scope."""

from __future__ import annotations

from teleclaude.caller_identity import (
    Platform,
    Project,
    RoleResolver,
    caller_from_principal,
    human_principal_for_email,
)
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.identity import CliCaller, PersonCliCaller, SystemCliCaller
from teleclaude.mirrors.store import ALL_MIRROR_ACCESS, MirrorAccess, PersonMirrorAccess
from teleclaude.services.project_catalog.service import get_project_catalog_service


def history_access_for_caller(caller: CliCaller) -> MirrorAccess | None:
    """Resolve all-mirror, project-admin, or principal-owned access for a caller."""
    if isinstance(caller, SystemCliCaller):
        return ALL_MIRROR_ACCESS
    if isinstance(caller, PersonCliCaller):
        if not caller.email:
            return None

        principal = human_principal_for_email(caller.email)
        role_caller = caller_from_principal(principal)
        if not isinstance(role_caller, PersonCliCaller):
            return None

        resolver = RoleResolver()
        if resolver.role_for(role_caller, Platform()) == HUMAN_ROLE_ADMIN:
            return ALL_MIRROR_ACCESS

        projects = frozenset(
            project.slug
            for project in get_project_catalog_service().list_projects()
            if resolver.role_for(role_caller, Project(project.slug)) == HUMAN_ROLE_ADMIN
        )
        return PersonMirrorAccess(email=caller.email, principal=principal, projects=projects)
    return None

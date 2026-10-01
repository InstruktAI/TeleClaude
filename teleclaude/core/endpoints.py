"""Endpoints a conversation enters: entry identifiers, desk locations, resolution and hosting.

This module is the only owner of what an entry identifier is, where each kind
of help desk lives, whether a desk is enabled on this computer, and which
computer hosts a desk. Placement, the conversation seam, the heartbeat, the
links command and context selection all ask it; none derives a desk folder or
parses an identifier on its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import list_company_config_paths, load_company_config, load_global_config
from teleclaude.core.models import EndpointKind, EndpointStamp, HelpDeskKind
from teleclaude.paths import (
    COMPANIES_ROOT,
    HELP_DESK_DIRNAME,
    PROJECTS_MANIFEST_PATH,
    TELECLAUDE_HOME,
    ConfigFileName,
)
from teleclaude.services.project_catalog.service import ProjectCatalogService

logger = get_logger(__name__)

# Telegram limits a start parameter to this many characters
# (`third-party/telegram/deep-linking`); a longer identifier has no Telegram link.
TELEGRAM_START_PARAMETER_MAX = 64

_DESK_IDENTIFIER_TEMPLATE = "hd-{kind}-{slug}"
_DESK_IDENTIFIER_PATTERN = re.compile(r"^hd-(company|project)-([a-z0-9]+(?:-[a-z0-9]+)*)$")
_INVITE_TOKEN_PATTERN = re.compile(r"^inv_[0-9a-f]{16}$")
_HOST_CONFLICT_EVENT = "help_desk_host_conflict"
_COMPANY_DECLARATION_UNREADABLE_EVENT = "help_desk_company_declaration_unreadable"


@dataclass(frozen=True)
class DeskIdentifier:
    """The entry identifier of a company's or a project's help desk."""

    kind: HelpDeskKind
    slug: str

    def render(self) -> str:
        """The identifier as a person sends or opens it."""
        return _DESK_IDENTIFIER_TEMPLATE.format(kind=self.kind.value, slug=self.slug)


@dataclass(frozen=True)
class InviteToken:
    """A member's invitation token: the entry identifier of that member's assistant."""

    token: str


EntryIdentifier = DeskIdentifier | InviteToken


def parse_entry_identifier(text: str) -> EntryIdentifier | None:
    """Parse text that is exactly an entry identifier, or return ``None``.

    Only surrounding whitespace is ignored. The platform desk has no
    identifier, and anything that is not exactly a company or project desk
    identifier or an invitation token — changed case, a typo, a missing slug —
    is no identifier.
    """
    candidate = text.strip()
    if _INVITE_TOKEN_PATTERN.match(candidate):
        return InviteToken(candidate)
    match = _DESK_IDENTIFIER_PATTERN.match(candidate)
    if match is None:
        return None
    return DeskIdentifier(HelpDeskKind(match.group(1)), match.group(2))


@dataclass(frozen=True)
class DeskRoots:
    """Where this computer keeps the homes whose desks it may host."""

    home: Path = TELECLAUDE_HOME
    companies_root: Path = COMPANIES_ROOT
    projects_manifest: Path = PROJECTS_MANIFEST_PATH


LIVE_ROOTS = DeskRoots()


@dataclass(frozen=True)
class Endpoint:
    """A routable destination: a person's assistant or a home's help desk, on its hosting computer.

    ``folder`` is the working folder on this computer; it is ``None`` for an
    endpoint hosted elsewhere, whose host resolves its own folder.
    """

    kind: EndpointKind
    host: str
    folder: Path | None = None
    desk_kind: HelpDeskKind | None = None
    slug: str | None = None
    person: str | None = None

    def to_stamp(self) -> EndpointStamp:
        """The stamp a session created at this endpoint carries."""
        return EndpointStamp(kind=self.kind, desk_kind=self.desk_kind, slug=self.slug, person=self.person)


def platform_help_desk_folder(roots: DeskRoots = LIVE_ROOTS) -> Path:
    """The platform help desk's folder in the runtime home."""
    return roots.home / HELP_DESK_DIRNAME


def company_help_desk_folder(slug: str, roots: DeskRoots = LIVE_ROOTS) -> Path:
    """A company's help desk folder, inside the company home."""
    return roots.companies_root / slug / HELP_DESK_DIRNAME


def project_help_desk_folder(root: Path) -> Path:
    """A project's help desk folder, inside the project root."""
    return root / HELP_DESK_DIRNAME


def platform_help_desk_enabled(roots: DeskRoots = LIVE_ROOTS) -> bool:
    """Whether the global declaration in the runtime home enables the platform help desk."""
    declaration = roots.home / ConfigFileName.OVERLAY
    return declaration.is_file() and load_global_config(declaration).help_desk.enabled


def _enabled_project_desks(roots: DeskRoots) -> Iterable[tuple[DeskIdentifier, Path]]:
    for node in ProjectCatalogService(manifest_path=roots.projects_manifest).list_projects():
        if node.config.help_desk.enabled:
            yield DeskIdentifier(HelpDeskKind.PROJECT, node.slug), project_help_desk_folder(node.root)


def _enabled_company_desks(roots: DeskRoots) -> Iterable[tuple[DeskIdentifier, Path]]:
    for declaration in list_company_config_paths(roots.companies_root):
        slug = declaration.parent.name
        try:
            enabled = load_company_config(declaration).help_desk.enabled
        except (OSError, ValueError) as exc:
            logger.warning(_COMPANY_DECLARATION_UNREADABLE_EVENT, company=slug, error=str(exc))
            continue
        if enabled:
            yield DeskIdentifier(HelpDeskKind.COMPANY, slug), company_help_desk_folder(slug, roots)


def _enabled_desks(roots: DeskRoots) -> list[tuple[DeskIdentifier, Path]]:
    return [*_enabled_company_desks(roots), *_enabled_project_desks(roots)]


def hosted_help_desks(roots: DeskRoots = LIVE_ROOTS) -> list[DeskIdentifier]:
    """The company and project desks enabled on this computer, in identifier order."""
    return sorted((identifier for identifier, _ in _enabled_desks(roots)), key=DeskIdentifier.render)


def _desk_endpoint(identifier: DeskIdentifier, folder: Path, host: str) -> Endpoint:
    return Endpoint(
        kind=EndpointKind.HELP_DESK,
        folder=folder,
        host=host,
        desk_kind=identifier.kind,
        slug=identifier.slug,
    )


def local_desk_endpoint(identifier: DeskIdentifier, host: str, roots: DeskRoots = LIVE_ROOTS) -> Endpoint | None:
    """The endpoint of a desk enabled on this computer, or ``None`` when it is not."""
    for enabled, folder in _enabled_desks(roots):
        if enabled == identifier:
            return _desk_endpoint(identifier, folder, host)
    return None


def platform_desk_endpoint(host: str, roots: DeskRoots = LIVE_ROOTS) -> Endpoint | None:
    """The platform help desk's endpoint when it is enabled, else ``None``."""
    if not platform_help_desk_enabled(roots):
        return None
    return Endpoint(
        kind=EndpointKind.HELP_DESK,
        folder=platform_help_desk_folder(roots),
        host=host,
        desk_kind=HelpDeskKind.PLATFORM,
    )


def desk_endpoint_for_stamp(stamp: EndpointStamp, host: str, roots: DeskRoots = LIVE_ROOTS) -> Endpoint | None:
    """This computer's endpoint for the desk a stamp names, when that desk is enabled here."""
    if not stamp.is_help_desk:
        return None
    if stamp.desk_kind is HelpDeskKind.PLATFORM:
        return platform_desk_endpoint(host, roots)
    if stamp.desk_kind is None or stamp.slug is None:
        return None
    return local_desk_endpoint(DeskIdentifier(stamp.desk_kind, stamp.slug), host, roots)


def stamp_desk_identifier(stamp: EndpointStamp) -> DeskIdentifier | None:
    """The entry identifier of the company or project desk a stamp names, if it names one."""
    if not stamp.is_tenant_desk or stamp.desk_kind is None or stamp.slug is None:
        return None
    return DeskIdentifier(stamp.desk_kind, stamp.slug)


def assistant_endpoint(person_slug: str, folder: Path, host: str) -> Endpoint:
    """A registered person's assistant, running in their home."""
    return Endpoint(kind=EndpointKind.ASSISTANT, folder=folder, host=host, person=person_slug)


def desk_for_folder(path: str | Path, host: str, roots: DeskRoots = LIVE_ROOTS) -> Endpoint | None:
    """The enabled help desk whose folder is exactly ``path``, or ``None``.

    Matches the folder itself only: never a subfolder, a sibling, or the
    folder of a desk that is not enabled.
    """
    resolved = Path(path).expanduser().resolve()
    platform = platform_desk_endpoint(host, roots)
    if platform is not None and platform.folder is not None and platform.folder.expanduser().resolve() == resolved:
        return platform
    for identifier, folder in _enabled_desks(roots):
        if folder.expanduser().resolve() == resolved:
            return _desk_endpoint(identifier, folder, host)
    return None


def desk_home_present(identifier: DeskIdentifier, roots: DeskRoots = LIVE_ROOTS) -> bool:
    """Whether the home a desk identifier names is held on this computer, enabled or not."""
    if identifier.kind is HelpDeskKind.COMPANY:
        return (roots.companies_root / identifier.slug / ConfigFileName.OVERLAY).is_file()
    return ProjectCatalogService(manifest_path=roots.projects_manifest).get_by_slug(identifier.slug) is not None


def resolve_host(identifier: DeskIdentifier, announcements: Mapping[str, Sequence[str]]) -> str | None:
    """The single computer announcing a desk, from every computer's announcement alike.

    ``announcements`` maps each live computer, this one included, to the desk
    identifiers it announces. No computer is preferred: one announcer hosts the
    desk, none means no host, and more than one is a misconfiguration that is
    refused, so every receiver sees the same miss.
    """
    rendered = identifier.render()
    announcers = sorted(computer for computer, desks in announcements.items() if rendered in desks)
    if len(announcers) > 1:
        logger.error(_HOST_CONFLICT_EVENT, identifier=rendered, computers=announcers)
        return None
    return announcers[0] if announcers else None


__all__ = [
    "LIVE_ROOTS",
    "TELEGRAM_START_PARAMETER_MAX",
    "DeskIdentifier",
    "DeskRoots",
    "Endpoint",
    "EntryIdentifier",
    "InviteToken",
    "assistant_endpoint",
    "company_help_desk_folder",
    "desk_endpoint_for_stamp",
    "desk_for_folder",
    "desk_home_present",
    "hosted_help_desks",
    "local_desk_endpoint",
    "parse_entry_identifier",
    "platform_desk_endpoint",
    "platform_help_desk_enabled",
    "platform_help_desk_folder",
    "project_help_desk_folder",
    "resolve_host",
    "stamp_desk_identifier",
]

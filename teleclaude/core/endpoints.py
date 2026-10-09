"""Endpoints a conversation enters: entry identifiers, desk locations, resolution and hosting.

This module is the only owner of what an entry identifier is, where each kind
of help desk lives, whether a desk is enabled on this computer, and which
computer hosts a desk: help desks run only on the mesh master, so a desk is
hosted here exactly when this computer is the master and the desk is enabled
in a home it holds. Placement, the conversation seam, the links command and
context selection all ask it; none derives a desk folder or parses an
identifier on its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import list_company_config_paths, load_company_config
from teleclaude.core.models import EndpointKind, EndpointStamp, HelpDeskKind
from teleclaude.paths import (
    COMPANIES_ROOT,
    HELP_DESK_DIRNAME,
    PROJECTS_MANIFEST_PATH,
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

    Only surrounding whitespace is ignored. Anything that is not exactly a
    company or project desk identifier or an invitation token — changed case,
    a typo, a missing slug — is no identifier.
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

    companies_root: Path = COMPANIES_ROOT
    projects_manifest: Path = PROJECTS_MANIFEST_PATH


LIVE_ROOTS = DeskRoots()


@dataclass(frozen=True)
class Endpoint:
    """A routable destination: a person's assistant or a home's help desk, on its hosting computer.

    ``folder`` is the working folder on this computer.
    """

    kind: EndpointKind
    host: str
    folder: Path
    desk_kind: HelpDeskKind | None = None
    slug: str | None = None
    person: str | None = None

    def to_stamp(self) -> EndpointStamp:
        """The stamp a session created at this endpoint carries."""
        return EndpointStamp(kind=self.kind, desk_kind=self.desk_kind, slug=self.slug, person=self.person)


def company_help_desk_folder(slug: str, roots: DeskRoots = LIVE_ROOTS) -> Path:
    """A company's help desk folder, inside the company home."""
    return roots.companies_root / slug / HELP_DESK_DIRNAME


def project_help_desk_folder(root: Path) -> Path:
    """A project's help desk folder, inside the project root."""
    return root / HELP_DESK_DIRNAME


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


def _desk_endpoint(identifier: DeskIdentifier, folder: Path, host: str) -> Endpoint:
    return Endpoint(
        kind=EndpointKind.HELP_DESK,
        folder=folder,
        host=host,
        desk_kind=identifier.kind,
        slug=identifier.slug,
    )


def local_desk_endpoint(
    identifier: DeskIdentifier, host: str, is_master: bool, roots: DeskRoots = LIVE_ROOTS
) -> Endpoint | None:
    """The endpoint of a desk this computer hosts, or ``None`` when it does not.

    A desk is hosted only on the master, and only when it is enabled in a home
    this computer holds.
    """
    if not is_master:
        return None
    for enabled, folder in _enabled_desks(roots):
        if enabled == identifier:
            return _desk_endpoint(identifier, folder, host)
    return None


def desk_endpoint_for_stamp(
    stamp: EndpointStamp, host: str, is_master: bool, roots: DeskRoots = LIVE_ROOTS
) -> Endpoint | None:
    """This computer's endpoint for the desk a stamp names, when it hosts that desk."""
    if not stamp.is_help_desk:
        return None
    if stamp.desk_kind is None or stamp.slug is None:
        return None
    return local_desk_endpoint(DeskIdentifier(stamp.desk_kind, stamp.slug), host, is_master, roots)


def assistant_endpoint(person_slug: str, folder: Path, host: str) -> Endpoint:
    """A registered person's assistant, running in their home."""
    return Endpoint(kind=EndpointKind.ASSISTANT, folder=folder, host=host, person=person_slug)


def _enabled_desk_at(resolved: Path, roots: DeskRoots) -> tuple[DeskIdentifier, Path] | None:
    for identifier, folder in _enabled_desks(roots):
        if folder.expanduser().resolve() == resolved:
            return identifier, folder
    return None


def desk_for_folder(path: str | Path, host: str, is_master: bool, roots: DeskRoots = LIVE_ROOTS) -> Endpoint | None:
    """The help desk this computer hosts whose folder is exactly ``path``, or ``None``.

    Matches the folder itself only: never a subfolder, a sibling, or the
    folder of a desk that is not enabled; a computer that is not the master
    hosts none.
    """
    if not is_master:
        return None
    resolved = Path(path).expanduser().resolve()
    match = _enabled_desk_at(resolved, roots)
    return _desk_endpoint(*match, host) if match is not None else None


def tenant_desk_for_folder(path: str | Path, roots: DeskRoots = LIVE_ROOTS) -> DeskIdentifier | None:
    """The enabled company or project desk whose folder is exactly ``path``, or ``None``.

    Matches as :func:`desk_for_folder` does, for a caller that needs which desk
    a folder is rather than an endpoint on a host.
    """
    match = _enabled_desk_at(Path(path).expanduser().resolve(), roots)
    return match[0] if match is not None else None


def desk_home_present(identifier: DeskIdentifier, roots: DeskRoots = LIVE_ROOTS) -> bool:
    """Whether the home a desk identifier names is held on this computer, enabled or not."""
    if identifier.kind is HelpDeskKind.COMPANY:
        return (roots.companies_root / identifier.slug / ConfigFileName.OVERLAY).is_file()
    return ProjectCatalogService(manifest_path=roots.projects_manifest).get_by_slug(identifier.slug) is not None


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
    "local_desk_endpoint",
    "parse_entry_identifier",
    "project_help_desk_folder",
    "tenant_desk_for_folder",
]

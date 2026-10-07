"""Which inbound sources a registered home declares, read fresh from the home's own configuration.

The configuration context owns which homes exist and what they declare. The
ingress asks this module by home kind and slug and never walks folders itself.
Every call reads the home's configuration and sibling `.env` again, so a
declaration added, changed or removed takes effect on the next call.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.config.loader import (
    find_company_config_path,
    load_company_config,
    load_global_config,
    load_person_config,
    load_project_config,
)
from teleclaude.config.schema import NativeInboundSources, WhatsAppInboundSource
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.paths import PEOPLE_DIR, ConfigFileName
from teleclaude.project_manifest import load_registered_roots
from teleclaude.slug import derive_project_slug, validate_slug

_UTF8 = "utf-8"
_PROJECT_SLUG_FIELD = "project_slug"
_PROJECT_NAME_FIELD = "project_name"
_GLOBAL_HOME = "global"
_HOME_DESCRIPTION = "{kind}/{slug}"
_LOAD_ERROR = "Cannot read the inbound sources declared by {home}: {cause}"


class InboundDeclarationError(Exception):
    """A registered home's configuration could not be read; its declared sources are unknown."""

    def __init__(self, home: str, cause: Exception) -> None:
        super().__init__(_LOAD_ERROR.format(home=home, cause=cause))
        self.home = home
        self.cause = cause


def declared_inbound_sources(kind: ConfigSubjectKind, slug: str) -> NativeInboundSources | None:
    """Answer the sources a registered company, person or project declares.

    Returns ``None`` when no such home is registered here. Returns the declared
    sources otherwise, a ``ProjectInboundSources`` for a project. Raises
    ``InboundDeclarationError`` when the home is registered but its configuration
    cannot be read, so a broken declaration is never mistaken for an absent one.
    """
    try:
        validate_slug(slug)
    except ValueError:
        return None
    home = _HOME_DESCRIPTION.format(kind=kind.value, slug=slug)
    try:
        return _read_declared_sources(kind, slug)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise InboundDeclarationError(home, exc) from exc


def declared_whatsapp_source() -> WhatsAppInboundSource | None:
    """Answer the WhatsApp source the global configuration declares, or ``None`` when it declares none."""
    try:
        return load_global_config().hooks.inbound.whatsapp
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise InboundDeclarationError(_GLOBAL_HOME, exc) from exc


def _read_declared_sources(kind: ConfigSubjectKind, slug: str) -> NativeInboundSources | None:
    if kind is ConfigSubjectKind.COMPANY:
        company_path = find_company_config_path(slug)
        return None if company_path is None else load_company_config(company_path).hooks.inbound
    if kind is ConfigSubjectKind.PERSON:
        person_path = PEOPLE_DIR / slug / ConfigFileName.OVERLAY
        if not person_path.is_file():
            return None
        return load_person_config(person_path, registered_slug=slug).hooks.inbound
    if kind is ConfigSubjectKind.PROJECT:
        project_path = _registered_project_declaration(slug)
        return None if project_path is None else load_project_config(project_path).hooks.inbound
    return None


def _registered_project_declaration(slug: str) -> Path | None:
    """Find the registered project root whose identity is ``slug``.

    A root's identity comes from its raw declaration, so a project whose
    configuration fails to load is still identified, and its failure surfaces
    from the load that follows.
    """
    for root in load_registered_roots():
        if root.is_present and _raw_project_identity(root.path) == slug:
            return root.path / ConfigFileName.OVERLAY
    return None


def _raw_project_identity(root: Path) -> str | None:
    declaration = root / ConfigFileName.OVERLAY
    try:
        document: object = yaml.safe_load(declaration.read_text(encoding=_UTF8))
    except (OSError, UnicodeError, yaml.YAMLError):
        return derive_project_slug(None, None, root)
    if not isinstance(document, dict):
        return derive_project_slug(None, None, root)
    return derive_project_slug(document.get(_PROJECT_SLUG_FIELD), document.get(_PROJECT_NAME_FIELD), root)

"""Which inbound sources a registered home declares, read fresh from the home's own configuration.

The configuration context owns which homes exist and what they declare. The
ingress asks this module by home kind and slug and never walks folders itself.
Every call reads the home's configuration and sibling `.env` again, so a
declaration added, changed or removed takes effect on the next call.
"""

from __future__ import annotations

import yaml

from teleclaude.config.loader import (
    load_company_config,
    load_global_config,
    load_person_config,
    load_project_config,
)
from teleclaude.config.registered_homes import registered_home_folder
from teleclaude.config.schema import NativeInboundSources, WhatsAppInboundSource
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.paths import ConfigFileName
from teleclaude.slug import validate_slug

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
    folder = registered_home_folder(kind, slug)
    if folder is None:
        return None
    declaration = folder / ConfigFileName.OVERLAY
    if kind is ConfigSubjectKind.COMPANY:
        return load_company_config(declaration).hooks.inbound
    if kind is ConfigSubjectKind.PERSON:
        return load_person_config(declaration, registered_slug=slug).hooks.inbound
    return load_project_config(declaration).hooks.inbound

"""Which template targets each home receives, derived from its declarations."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.loader import load_company_config, load_global_config
from teleclaude.config.schema import ConfigKind
from teleclaude.core.reconciliation.template_installation import TemplateTarget
from teleclaude.paths import HELP_DESK_DIRNAME, ConfigFileName
from teleclaude.snippet_roots import iter_declared_tier_roots

TemplateTargets = tuple[tuple[Path, TemplateTarget], ...]


def person_home_targets(root: Path) -> TemplateTargets:
    """A person home receives its documentation baselines and the person master."""
    return ((root, TemplateTarget.PERSON_HOME),)


def company_home_targets(root: Path) -> TemplateTargets:
    """A company home, plus its help desk when its declaration enables one."""
    targets: TemplateTargets = ((root, TemplateTarget.COMPANY_HOME),)
    if load_company_config(root / ConfigFileName.OVERLAY).help_desk.enabled:
        targets += ((root / HELP_DESK_DIRNAME, TemplateTarget.COMPANY_HELP_DESK),)
    return targets


def platform_help_desk_targets(home: Path) -> TemplateTargets:
    """The platform help desk, when the global declaration exists and enables it."""
    declaration = home / ConfigFileName.OVERLAY
    if declaration.is_file() and load_global_config(declaration).help_desk.enabled:
        return ((home / HELP_DESK_DIRNAME, TemplateTarget.PLATFORM_HELP_DESK),)
    return ()


def project_targets(root: Path, *, docs: bool, help_desk: bool) -> TemplateTargets:
    """A project's documentation baselines and help desk, as its caller decides; installation never calls this."""
    targets: TemplateTargets = ()
    if docs:
        targets += ((root, TemplateTarget.PROJECT),)
    if help_desk:
        targets += ((root / HELP_DESK_DIRNAME, TemplateTarget.PROJECT_HELP_DESK),)
    return targets


def home_installation_targets(home: Path) -> TemplateTargets:
    """Every target machine installation converges: the home, each declared tier home, the platform desk.

    The home itself never receives the documentation layer: its ``docs/`` is the
    published documentation generation.
    """
    targets: TemplateTargets = ((home, TemplateTarget.TELECLAUDE_HOME),)
    for root, kind in iter_declared_tier_roots(home):
        targets += company_home_targets(root) if kind is ConfigKind.COMPANY else person_home_targets(root)
    return targets + platform_help_desk_targets(home)


__all__ = [
    "company_home_targets",
    "home_installation_targets",
    "person_home_targets",
    "platform_help_desk_targets",
    "project_targets",
]

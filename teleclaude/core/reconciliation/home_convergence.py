"""Which template targets each home receives, derived from its declarations."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.loader import load_company_config
from teleclaude.config.schema import ConfigKind
from teleclaude.core.reconciliation.template_installation import TemplateTarget
from teleclaude.paths import HELP_DESK_DIRNAME, ConfigFileName
from teleclaude.snippet_roots import iter_declared_tier_roots

TemplateTargets = tuple[tuple[Path, TemplateTarget], ...]


def person_baseline_targets(root: Path) -> TemplateTargets:
    """A person home's documentation baselines, created once and then curated by the home."""
    return ((root, TemplateTarget.PERSON_HOME),)


def person_master_targets(root: Path) -> TemplateTargets:
    """A person home's master, seeded once from its kind's template and then owned by the home."""
    return ((root, TemplateTarget.PERSON_MASTER),)


def company_baseline_targets(root: Path) -> TemplateTargets:
    """A company home's documentation baselines, created once and then curated by the home."""
    return ((root, TemplateTarget.COMPANY_HOME),)


def company_master_targets(root: Path) -> TemplateTargets:
    """A company home's master, seeded once from its kind's template and then owned by the home."""
    return ((root, TemplateTarget.COMPANY_MASTER),)


def company_help_desk_targets(root: Path) -> TemplateTargets:
    """A company's help desk, when its declaration enables one."""
    if load_company_config(root / ConfigFileName.OVERLAY).help_desk.enabled:
        return ((root / HELP_DESK_DIRNAME, TemplateTarget.COMPANY_HELP_DESK),)
    return ()


def person_home_targets(root: Path) -> TemplateTargets:
    """A new person home receives its documentation baselines and its master."""
    return person_baseline_targets(root) + person_master_targets(root)


def company_home_targets(root: Path) -> TemplateTargets:
    """A new company home receives its documentation baselines and its master, plus its help desk when enabled."""
    return company_baseline_targets(root) + company_master_targets(root) + company_help_desk_targets(root)


def project_targets(root: Path, *, docs: bool, help_desk: bool) -> TemplateTargets:
    """A project's documentation baselines and help desk, as its caller decides; installation never calls this."""
    targets: TemplateTargets = ()
    if docs:
        targets += ((root, TemplateTarget.PROJECT),)
    if help_desk:
        targets += ((root / HELP_DESK_DIRNAME, TemplateTarget.PROJECT_HELP_DESK),)
    return targets


def home_installation_targets(home: Path) -> TemplateTargets:
    """Every target machine installation converges: the home's repository layer and each declared tier home's baselines.

    The home itself never receives the documentation layer: its ``docs/`` is the
    published documentation generation. The masters a home seeds are not
    installed (``home_output_targets``).
    """
    targets: TemplateTargets = ((home, TemplateTarget.TELECLAUDE_HOME),)
    for root, kind in iter_declared_tier_roots(home):
        targets += company_baseline_targets(root) if kind is ConfigKind.COMPANY else person_baseline_targets(root)
    return targets


def home_output_targets(home: Path) -> TemplateTargets:
    """The masters a home's declarations seed: each tier home's master and each enabled company help desk."""
    targets: TemplateTargets = ()
    for root, kind in iter_declared_tier_roots(home):
        if kind is ConfigKind.COMPANY:
            targets += company_master_targets(root) + company_help_desk_targets(root)
        else:
            targets += person_master_targets(root)
    return targets


__all__ = [
    "company_baseline_targets",
    "company_help_desk_targets",
    "company_home_targets",
    "company_master_targets",
    "home_installation_targets",
    "home_output_targets",
    "person_baseline_targets",
    "person_home_targets",
    "person_master_targets",
    "project_targets",
]

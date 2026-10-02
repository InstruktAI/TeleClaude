"""Enable a home's help desk in its declaration and converge the help desk it keeps."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from teleclaude.config.declaration import render_declared_config
from teleclaude.config.migrations import upcast
from teleclaude.config.resource_catalog import load_mapping
from teleclaude.config.resource_contract import InvalidCandidate, OwnEvidence, carry_resource_migrations
from teleclaude.config.schema import CompanyConfig, ConfigKind
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.reconciliation.home_convergence import company_home_targets, platform_help_desk_targets
from teleclaude.core.reconciliation.template_installation import materialize_template_targets
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import ConfigFileName

HELP_DESK_KEY = "help_desk"
_ENABLED_KEY = "enabled"
_KIND_KEY = "kind"


def with_help_desk_enabled(document: Mapping[str, object]) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Return ``document`` with its help desk enabled and every other value kept."""
    current = document.get(HELP_DESK_KEY)
    section = dict(current) if isinstance(current, Mapping) else {}
    section[_ENABLED_KEY] = True
    return {**document, HELP_DESK_KEY: section}


def enable_company_help_desk(company_dir: Path, evidence: OwnEvidence) -> None:
    """Record the company's help desk as enabled when it is not, then converge the home and its desk."""
    ref = SubjectRef(ConfigSubjectKind.COMPANY, company_dir.name)
    path = company_dir / ConfigFileName.OVERLAY
    with file_transaction(path) as transaction:
        stored = load_mapping(transaction.read_text(), path)
        current = dict(upcast(stored, ref))
        candidate = with_help_desk_enabled(current)
        if candidate != current:
            try:
                CompanyConfig.model_validate({**candidate, _KIND_KEY: ConfigKind.COMPANY.value})
            except Exception as exc:
                raise InvalidCandidate(str(exc)) from exc
            carry_resource_migrations(stored, ref, evidence)
            transaction.replace_text(render_declared_config(ConfigKind.COMPANY, candidate))
    materialize_template_targets(company_home_targets(company_dir), values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation


def converge_platform_help_desk(home: Path) -> None:
    """Converge the platform help desk when the global declaration in ``home`` enables it."""
    targets = platform_help_desk_targets(home)
    if targets:
        materialize_template_targets(targets, values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation


__all__ = ["HELP_DESK_KEY", "converge_platform_help_desk", "enable_company_help_desk", "with_help_desk_enabled"]

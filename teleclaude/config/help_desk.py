"""Enable a home's help desk in its declaration and converge the help desk it keeps."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from teleclaude.core.reconciliation.home_convergence import platform_help_desk_targets
from teleclaude.core.reconciliation.template_installation import materialize_template_targets

HELP_DESK_KEY = "help_desk"
_ENABLED_KEY = "enabled"


def with_help_desk_enabled(document: Mapping[str, object]) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Return ``document`` with its help desk enabled and every other value kept."""
    current = document.get(HELP_DESK_KEY)
    section = dict(current) if isinstance(current, Mapping) else {}
    section[_ENABLED_KEY] = True
    return {**document, HELP_DESK_KEY: section}


def converge_platform_help_desk(home: Path) -> None:
    """Converge the platform help desk when the global declaration in ``home`` enables it."""
    targets = platform_help_desk_targets(home)
    if targets:
        materialize_template_targets(targets, values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation


__all__ = ["HELP_DESK_KEY", "converge_platform_help_desk", "with_help_desk_enabled"]

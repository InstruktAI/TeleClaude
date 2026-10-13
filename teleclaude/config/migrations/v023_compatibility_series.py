"""Replace the stable minor pin with the compatibility series it selects."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 23
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_DEPLOYMENT = "deployment"
_PINNED_MINOR = "pinned_minor"
_COMPATIBILITY_SERIES = "compatibility_series"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Move `deployment.pinned_minor` to `deployment.compatibility_series`, naming the boundary it selects.

    A pre-1.0 pin keeps its minor line and a positive-major pin becomes that major's line. An empty pin
    declares no series. Any other text, including an environment reference, is carried verbatim, so the
    configuration boundary that expands it decides its meaning. A series already declared wins.
    """
    deployment = document.get(_DEPLOYMENT)
    if not isinstance(deployment, MutableMapping) or _PINNED_MINOR not in deployment:
        return
    pinned = deployment.pop(_PINNED_MINOR)
    if _COMPATIBILITY_SERIES in deployment or not pinned:
        return
    deployment[_COMPATIBILITY_SERIES] = _series_text(str(pinned))


def _series_text(pin: str) -> str:
    """The series a literal pin selects, or the pin unchanged when it is not a literal minor pin."""
    try:
        return str(CompatibilitySeries.parse(pin))
    except ValueError:
        return pin

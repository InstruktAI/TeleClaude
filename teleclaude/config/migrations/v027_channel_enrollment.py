"""Enroll every earlier release-channel declaration on edge or stable and drop the declared series."""

from __future__ import annotations

from collections.abc import MutableMapping
from enum import StrEnum
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 27
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_DEPLOYMENT = "deployment"
_CHANNEL = "channel"
_COMPATIBILITY_SERIES = "compatibility_series"


class _Channel(StrEnum):
    """The channel spellings this step reads and writes."""

    ALPHA = "alpha"
    BETA = "beta"
    EDGE = "edge"
    STABLE = "stable"


_RENAMED: Final[dict[str, str]] = {
    _Channel.ALPHA.value: _Channel.EDGE.value,
    _Channel.BETA.value: _Channel.STABLE.value,
}


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Keep what the installation follows: alpha becomes edge, beta becomes stable, an omitted channel edge.

    An omitted deployment block or channel followed main, so it becomes explicit edge; a channel already
    spelled edge or stable is kept. The series stops gating a stable installation and is dropped on every
    channel. A deployment value that is not a mapping, or a channel spelled any other way, is left for
    validation to name.
    """
    deployment = document.get(_DEPLOYMENT)
    if deployment is None:
        deployment = {}
        document[_DEPLOYMENT] = deployment
    if not isinstance(deployment, MutableMapping):
        return
    deployment.pop(_COMPATIBILITY_SERIES, None)
    declared = deployment.get(_CHANNEL)
    if declared is None:
        deployment[_CHANNEL] = _Channel.EDGE.value
        return
    renamed = _RENAMED.get(declared) if isinstance(declared, str) else None
    if renamed is not None:
        deployment[_CHANNEL] = renamed

"""Restore the operator-configured loopback API port."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from enum import StrEnum
from typing import Final, cast

from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 12
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False


class _ConfigField(StrEnum):
    """Machine configuration keys used by this migration."""

    API = "api"
    TCP_PORT = "tcp_port"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Ensure computer documents carry the default API TCP port."""
    if _ConfigField.API not in document:
        document[_ConfigField.API] = {}

    api = document[_ConfigField.API]
    if not isinstance(api, MutableMapping) or _ConfigField.TCP_PORT in api:
        return

    api_defaults = cast(Mapping[str, object], DEFAULT_CONFIG[_ConfigField.API])
    api[_ConfigField.TCP_PORT] = api_defaults[_ConfigField.TCP_PORT]

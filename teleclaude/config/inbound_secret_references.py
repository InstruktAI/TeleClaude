"""An inbound signing secret is a reference to the declaring home's own `.env`, never a literal value.

A home's `teleclaude.yml` can be committed, so a literal signing secret in it
would put the endpoint's key into version control. The check reads the raw
document, before environment expansion, because the expanded model cannot tell a
resolved reference from a literal.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from teleclaude.config._environment import environment_reference_at_path
from teleclaude.config.schema import GlobalInboundSources, ProjectInboundSources

_HOOKS: Final = "hooks"
_INBOUND: Final = "inbound"
_SECRET: Final = "secret"
_PROTOCOLS: Final = tuple(dict.fromkeys((*ProjectInboundSources.model_fields, *GlobalInboundSources.model_fields)))
_LITERAL_SECRET_ERROR: Final = (
    "{path}: hooks.inbound.{protocol}.secret must be a ${{NAME}} reference resolved from this home's .env, "
    "not a literal value"
)


def require_inbound_secret_references(path: Path, document: Mapping[str, object]) -> None:
    """Refuse a raw overlay whose declared inbound signing secret is not a pure ``${NAME}`` reference.

    The error names the file and protocol and never carries the offending value.
    """
    hooks = document.get(_HOOKS)
    inbound = hooks.get(_INBOUND) if isinstance(hooks, Mapping) else None
    if not isinstance(inbound, Mapping):
        return
    for protocol in _PROTOCOLS:
        source = inbound.get(protocol)
        if not isinstance(source, Mapping) or not isinstance(source.get(_SECRET), str):
            continue
        if environment_reference_at_path(document, (_HOOKS, _INBOUND, protocol, _SECRET)) is None:
            raise ValueError(_LITERAL_SECRET_ERROR.format(path=path, protocol=protocol))

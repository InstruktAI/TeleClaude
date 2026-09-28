"""Remote computer config model and parser."""

from __future__ import annotations

from teleclaude.closed_model import ClosedModel
from teleclaude.config._coerce import TEXT, TRUTHY_TEXT


class RemoteComputerConfig(ClosedModel):
    """Configuration for a remote computer defined in config."""

    name: TEXT
    user: TRUTHY_TEXT = None
    host: TRUTHY_TEXT = None
    ip: TRUTHY_TEXT = None
    teleclaude_path: TRUTHY_TEXT = None

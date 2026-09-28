"""The closed validation posture shared by configuration models.

Hosted as a leaf module, not inside ``teleclaude.config``, because
``teleclaude.events.domain_config`` must inherit it without creating a reverse
import edge back into the config package.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ClosedModel(BaseModel):
    """A model that rejects undeclared keys instead of silently accepting them."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

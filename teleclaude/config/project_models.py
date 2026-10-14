"""Small project-scoped configuration value models."""

from __future__ import annotations

from typing import Literal

from teleclaude.closed_model import ClosedModel


class CapabilityConfig(ClosedModel):
    """Subscription state; an omitted block makes no capability claim."""

    enabled: bool = False


class TodoStoreConfig(ClosedModel):
    """Project selection for the workflow store adapter."""

    store: Literal["local", "github"] = "local"

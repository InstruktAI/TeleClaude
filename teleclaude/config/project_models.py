"""Small project-scoped configuration value models."""

from __future__ import annotations

from enum import StrEnum

from teleclaude.closed_model import ClosedModel


class CapabilityConfig(ClosedModel):
    """Subscription state; an omitted block makes no capability claim."""

    enabled: bool = False


class TodoStoreBackend(StrEnum):
    LOCAL = "local"
    GITHUB = "github"


class TodoStoreConfig(ClosedModel):
    """Project selection for the workflow store adapter."""

    store: TodoStoreBackend = TodoStoreBackend.LOCAL

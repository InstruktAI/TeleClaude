"""In-daemon workflow startup values; these never cross a command or public request wire."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from teleclaude.core.workflow_store.types import StoreAddress, WorkItemId
from teleclaude.types.github_binding import AdmittedWorkflowParent, GitHubWorkTarget

WORKFLOW_CREATION_FIELD = "workflow_creation"
_INTERNAL_INPUT_REFUSED = "Workflow creation context is internal to the owning daemon"
_POPULATED_WIRE_REFUSED = "Populated workflow creation context requires direct in-daemon creation, not serialization"
_INVALID_ITEM = "Workflow creation requires the owner's nonempty opaque item identity and address"
_INVALID_PARENT = "An admitted child requires its owner's qualified workflow-parent context"
_INVALID_TARGET = "Workflow creation requires an owner-projected target or explicit absence"


@dataclass(frozen=True, kw_only=True)
class WorkflowDriverCreation:
    """The activation owner's item pair and optional local-backend target absence."""

    item_id: WorkItemId
    store_address: StoreAddress
    target: GitHubWorkTarget | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(cast(object, value), str) or not value for value in (self.item_id, self.store_address)):
            raise ValueError(_INVALID_ITEM)
        if self.target is not None and not isinstance(cast(object, self.target), GitHubWorkTarget):
            raise ValueError(_INVALID_TARGET)


@dataclass(frozen=True, kw_only=True)
class WorkflowChildCreation(WorkflowDriverCreation):
    """The child owner's item pair plus its required admitted parent, without new eligibility rules."""

    parent: AdmittedWorkflowParent

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(cast(object, self.parent), AdmittedWorkflowParent):
            raise ValueError(_INVALID_PARENT)


def reject_workflow_creation_input(value: object) -> object:
    """Reject key presence even when null, before any decoder discards unknown fields."""
    if isinstance(value, Mapping) and WORKFLOW_CREATION_FIELD in value:
        raise ValueError(_INTERNAL_INPUT_REFUSED)
    return value


def refuse_workflow_creation_serialization() -> None:
    """A populated producer value cannot disappear into an apparently successful wire handoff."""
    raise ValueError(_POPULATED_WIRE_REFUSED)

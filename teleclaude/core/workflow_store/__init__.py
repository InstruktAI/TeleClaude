"""Backend-neutral boundary for project workflow state.

The package root stays light so validation-only callers do not import the
SQLite/ORM runtime. Export resolution is restricted to the declared public
names below.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .local import (
        check_local_database_integrity,
        get_local_transfer_source,
        local_database_location,
        local_store_presence,
        read_local_validation_status_rows,
    )
    from .store import (
        StoreUnavailable,
        WorkflowStore,
        close_workflow_stores,
        get_workflow_store,
        get_workflow_store_sync,
        set_workflow_store_mutation_hook,
        write_workflow_artifact_sync,
    )
    from .types import (
        ArtifactFile,
        ArtifactVersion,
        ClaimHolder,
        DeliveryRecord,
        GroupMembership,
        StoreAddress,
        StoreCapabilities,
        StorePresence,
        StorePresenceKind,
        TodoProjectionItem,
        TodoProjectionMetrics,
        TodoProjectionSnapshot,
        TransferResult,
        TransferSource,
        WorkItemId,
    )

_EXPORT_MODULES = {
    "check_local_database_integrity": ".local",
    "get_local_transfer_source": ".local",
    "local_database_location": ".local",
    "local_store_presence": ".local",
    "read_local_validation_status_rows": ".local",
    "StoreUnavailable": ".store",
    "WorkflowStore": ".store",
    "close_workflow_stores": ".store",
    "get_workflow_store": ".store",
    "get_workflow_store_sync": ".store",
    "set_workflow_store_mutation_hook": ".store",
    "write_workflow_artifact_sync": ".store",
    "ArtifactVersion": ".types",
    "ClaimHolder": ".types",
    "DeliveryRecord": ".types",
    "GroupMembership": ".types",
    "StoreAddress": ".types",
    "StoreCapabilities": ".types",
    "StorePresence": ".types",
    "StorePresenceKind": ".types",
    "TransferResult": ".types",
    "TransferSource": ".types",
    "WorkItemId": ".types",
}

__all__ = [
    "ArtifactFile",
    "ArtifactVersion",
    "ClaimHolder",
    "DeliveryRecord",
    "GroupMembership",
    "StoreAddress",
    "StoreCapabilities",
    "StorePresence",
    "StorePresenceKind",
    "StoreUnavailable",
    "TodoProjectionItem",
    "TodoProjectionMetrics",
    "TodoProjectionSnapshot",
    "TransferResult",
    "TransferSource",
    "WorkItemId",
    "WorkflowStore",
    "check_local_database_integrity",
    "close_workflow_stores",
    "get_local_transfer_source",
    "get_workflow_store",
    "get_workflow_store_sync",
    "local_database_location",
    "local_store_presence",
    "read_local_validation_status_rows",
    "set_workflow_store_mutation_hook",
    "write_workflow_artifact_sync",
]


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    return getattr(module, name)

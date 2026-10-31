"""Todo lifecycle database for todo state and text artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.core.workflow_store.types import IdentityResolution as TodoIdentityResolution
from teleclaude.core.workflow_store.types import StoreCapabilities

from ._artifacts import TodosDbArtifactsMixin, malformed_digest_detail
from ._base import TodosDbBase
from ._commit_reviews import TodosDbCommitReviewsMixin
from ._errors import (
    GroupCycleRefused,
    GroupDependencyConflict,
    HolderReconciliationRefused,
    HolderTransitionRefused,
    HolderWriteRefused,
)
from ._identity_pin import todo_identity_pin
from ._integration import TodosDbIntegrationMixin
from ._projection import TodosDbProjectionMixin
from ._rows import ArtifactMetadataRow, ArtifactVersionRow, ArtifactWritersRow, TodoRow
from ._state import TodosDbStateMixin
from ._todo import TodosDbTodoMixin
from ._todo_soft_delete import (
    TodoIdentityActionRefused,
    TodoIdentityNotFound,
    TodosDbTodoSoftDeleteMixin,
)
from ._todo_unfreeze import TodosDbTodoUnfreezeMixin
from ._workflow_operations import TodosDbWorkflowOperationsMixin


class TodosDb(
    TodosDbCommitReviewsMixin,
    TodosDbArtifactsMixin,
    TodosDbTodoUnfreezeMixin,
    TodosDbTodoMixin,
    TodosDbTodoSoftDeleteMixin,
    TodosDbStateMixin,
    TodosDbIntegrationMixin,
    TodosDbProjectionMixin,
    TodosDbWorkflowOperationsMixin,
    TodosDbBase,
):
    """Database interface for todo lifecycle state and artifacts."""

    async def admit_item_write(
        self, *, slug: str | None = None, todo_id: str | None = None, retained: bool = False
    ) -> None:
        """Refuse a write to the addressed item when the store cannot take it yet; the local store always can.

        `slug` addresses its live item, or with `retained` the newest retained one; `todo_id` addresses its item.
        """

    @property
    def project_root(self) -> Path:
        """Return the canonical project root without exposing its database path."""
        return self._db_path.parent.parent if self._db_path.parent.name == ".teleclaude" else self._db_path.parent

    @property
    def capabilities(self) -> StoreCapabilities:
        """Describe the operations implemented by the local adapter."""
        return StoreCapabilities(
            local_items=True,
            claims=True,
            phases=True,
            artifacts=True,
            revision_stamps=True,
            trail=True,
            delivery_candidates=True,
            incremental_replica_transfer=True,
        )

    def set_workflow_hooks(
        self,
        on_mutation: Callable[[str, Mapping[str, object] | None], None],
        on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None],
        on_delivered: Callable[[str, str | None, str], None],
    ) -> None:
        """Install the workflow event observers on this canonical local store."""
        self._on_mutation = on_mutation
        self._on_phase_transition = on_phase_transition
        self._on_delivered = on_delivered

    @contextmanager
    def identity_scope(self, slug: str, todo_id: str) -> Iterator[None]:
        """Pin an identity-addressed operation without publishing the DB path."""
        with todo_identity_pin(db_path=self.db_path, slug=slug, todo_id=todo_id):
            yield

    def notify_committed(
        self,
        event_hint: str = "todo_updated",
        event_data: Mapping[str, object] | None = None,
    ) -> None:
        """Publish the existing mutation event after a caller-owned commit."""
        self.on_committed(event_hint, event_data)


_instances: dict[str, TodosDb] = {}

# Hook called whenever get_todos_db or get_todos_db_sync creates a new instance.
# The daemon registers a hook that wires instance._on_mutation to its cache
# refresh. None in CLI and test contexts.
_new_instance_hook: Callable[[TodosDb, str], None] | None = None


def set_todos_mutation_hook(hook: Callable[[TodosDb, str], None] | None) -> None:
    """Register (or clear) the hook called when a new TodosDb instance is created.

    The daemon uses this to wire cache invalidation into every TodosDb instance
    so that local DB mutations immediately refresh the TUI todos pane.

    Args:
        hook: Callable receiving (instance, project_root), or None to clear.
    """
    global _new_instance_hook
    _new_instance_hook = hook


async def get_todos_db(project_root_or_cwd: str | Path) -> TodosDb:
    """Return a TodosDb instance for the canonical state root, creating if needed."""
    db_path = todos_db_path(project_root_or_cwd)
    key = str(db_path)
    if key not in _instances:
        instance = TodosDb(key)
        await instance.initialize()
        if _new_instance_hook is not None:
            _new_instance_hook(instance, str(db_path.parent.parent))
        _instances[key] = instance
    return _instances[key]


async def close_todos_db_instances() -> None:
    """Close and clear memoized todo DB instances for one-shot CLI commands."""
    instances = list(_instances.values())
    _instances.clear()
    for instance in instances:
        await instance.close()


def get_todos_db_sync(project_root_or_cwd: str | Path) -> TodosDb:
    """Sync sibling of get_todos_db: resolve project root, return cached TodosDb."""
    db_path = todos_db_path(project_root_or_cwd)
    key = str(db_path)
    if key not in _instances:
        instance = TodosDb(key)
        instance.initialize_sync()
        if _new_instance_hook is not None:
            _new_instance_hook(instance, str(db_path.parent.parent))
        _instances[key] = instance
    return _instances[key]


__all__ = [
    "ArtifactMetadataRow",
    "ArtifactVersionRow",
    "ArtifactWritersRow",
    "GroupCycleRefused",
    "GroupDependencyConflict",
    "HolderReconciliationRefused",
    "HolderTransitionRefused",
    "HolderWriteRefused",
    "TodoIdentityActionRefused",
    "TodoIdentityNotFound",
    "TodoIdentityResolution",
    "TodoRow",
    "TodosDb",
    "close_todos_db_instances",
    "get_todos_db",
    "get_todos_db_sync",
    "malformed_digest_detail",
    "set_todos_mutation_hook",
    "todos_db_path",
]

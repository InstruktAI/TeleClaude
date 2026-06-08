"""Small support helpers shared by prepare step handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.output_formatting import format_prepared
from teleclaude.core.next_machine.runtime.sessions import (
    find_live_prepare_worker_for_slug,
    find_live_root_next_prepare_session_for_slug,
    find_live_root_prepare_lifecycle_sessions_for_slug,
)
from teleclaude.core.next_machine.slug_resolution import (
    _is_prepare_runnable_lifecycle,
    deps_satisfied,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.next_machine.state_mutation import StateWriter

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.todos_db import TodosDb


def worker_idle_post_block(slug: str) -> str:
    """Post-block emitted after dispatching a worker."""
    return f"WHEN WORKER IDLES:\nCall telec todo prepare {slug}. The state machine emits the next action."


def reviewer_idle_post_block(slug: str) -> str:
    """Post-block emitted after dispatching a reviewer."""
    return (
        f"WHEN REVIEWER IDLES:\n"
        f"Call telec todo prepare {slug}. The state machine will read the verdict and emit the next action."
    )


def derive_project_root(cwd: str, slug: str) -> str:
    """Extract canonical project root from an effective cwd that may be a worktree."""
    suffix = f"/{WORKTREE_DIR}/{slug}"
    if cwd.endswith(suffix):
        return cwd[: -len(suffix)]
    return cwd


async def commit_writer(
    writer: StateWriter,
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
) -> None:
    """Commit the writer and sync the validated payload back to *state*."""
    payload = await writer.commit(todos_db, slug)
    state.clear()
    state.update(payload)


async def _unblocked_prepare_children(todos_db: TodosDb, parent_slug: str) -> list[str]:
    """Return direct dependents newly eligible for prepare after ``parent_slug`` reached PREPARED."""
    dependencies = await todos_db.load_deps()
    prepared = await effective_prepared_slugs_for_dependencies(todos_db)
    unblocked: list[str] = []
    for child_slug, after_slugs in dependencies.items():
        if parent_slug not in after_slugs:
            continue
        if not deps_satisfied(dependencies, prepared, child_slug):
            continue
        if _is_prepare_runnable_lifecycle(await todos_db.read_state(child_slug)):
            unblocked.append(child_slug)
    return sorted(unblocked)


async def build_prepare_autocontinue(
    db: Db,
    *,
    parent_slug: str,
    child_slug: str,
    project_root: str,
) -> tuple[str, str | None]:
    """Return the concrete operation for continuing prepare into ``child_slug``."""
    worker_id = await find_live_prepare_worker_for_slug(db, parent_slug, SlashCommand.NEXT_PREPARE.value)
    if worker_id is not None:
        message = (
            f"{parent_slug} is PREPARED and frozen in your context; drive prepare for unblocked child "
            f"{child_slug}: telec todo prepare {child_slug}"
        )
        escaped = message.replace('"', '\\"')
        return f'telec sessions send {worker_id} "{escaped}"', worker_id
    return f"telec sessions run --command /next-prepare --args {child_slug} --project {project_root}", None


async def prepare_step_prepared(db: Db, todos_db: TodosDb, slug: str, *, project_root: str) -> tuple[bool, str]:
    """PREPARED: terminal success state. Emits cleanup for all live slug sessions + self-end."""
    live_sessions = await find_live_root_prepare_lifecycle_sessions_for_slug(db, slug)
    self_end_session = await find_live_root_next_prepare_session_for_slug(db, slug)
    operations: list[str] = []
    reused_workers: set[str] = set()
    for child_slug in await _unblocked_prepare_children(todos_db, slug):
        operation, reused_worker = await build_prepare_autocontinue(
            db,
            parent_slug=slug,
            child_slug=child_slug,
            project_root=project_root,
        )
        operations.append(operation)
        if reused_worker is not None:
            reused_workers.add(reused_worker)

    excluded_from_id_cleanup = set(reused_workers)
    if self_end_session is not None:
        excluded_from_id_cleanup.add(self_end_session)
    session_ids_to_end = [session_id for session_id in live_sessions if session_id not in excluded_from_id_cleanup]
    return False, format_prepared(
        slug,
        session_ids_to_end=session_ids_to_end,
        auto_continue_operations=operations,
        suppress_self_end=bool(reused_workers),
    )

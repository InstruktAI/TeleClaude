"""Small support helpers shared by prepare step handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.output_formatting import format_prepared
from teleclaude.core.next_machine.runtime.sessions import (
    find_live_root_next_prepare_session_for_slug,
    find_live_root_prepare_lifecycle_sessions_for_slug,
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


async def prepare_step_prepared(db: Db, todos_db: TodosDb, slug: str, *, project_root: str) -> tuple[bool, str]:
    """PREPARED: terminal success state. Emits cleanup for all live slug sessions + self-end."""
    _ = todos_db, project_root
    live_sessions = await find_live_root_prepare_lifecycle_sessions_for_slug(db, slug)
    self_end_session = await find_live_root_next_prepare_session_for_slug(db, slug)
    excluded_from_id_cleanup: set[str] = set()
    if self_end_session is not None:
        excluded_from_id_cleanup.add(self_end_session)
    session_ids_to_end = [session_id for session_id in live_sessions if session_id not in excluded_from_id_cleanup]
    return False, format_prepared(
        slug,
        session_ids_to_end=session_ids_to_end,
    )

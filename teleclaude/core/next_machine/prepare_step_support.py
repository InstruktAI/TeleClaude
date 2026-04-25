"""Small support helpers shared by prepare step handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.output_formatting import format_prepared
from teleclaude.core.next_machine.runtime.sessions import find_all_live_sessions_for_slug
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


async def artifact_changed_since_state(
    todos_db: TodosDb,
    slug: str,
    artifact_name: str,
    state_digest: str,
) -> str | None:
    """Return the new DB digest when a worker produced new artifact content.

    Compares the current DB digest against the state digest (hydrated by
    mark-phase or set by a prior lifecycle pass). Returns the new digest when
    the artifact is new or changed, None when the artifact is absent or
    unchanged (stale from a previous pass).
    """
    if not await todos_db.artifact_exists(slug, artifact_name):
        return None
    db_digest = await todos_db.artifact_digest(slug, artifact_name)
    if db_digest and (not state_digest or db_digest != state_digest):
        return db_digest
    return None


async def prepare_step_prepared(db: Db, slug: str) -> tuple[bool, str]:
    """PREPARED: terminal success state. Emits cleanup for all live slug sessions + self-end."""
    live_sessions = await find_all_live_sessions_for_slug(db, slug)
    return False, format_prepared(slug, session_ids_to_end=live_sessions)

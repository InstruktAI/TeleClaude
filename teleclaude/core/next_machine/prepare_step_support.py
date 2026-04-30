"""Small support helpers shared by prepare step handlers."""

from __future__ import annotations

from pathlib import Path
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


def derive_worktree_cwd(cwd: str, slug: str) -> str:
    """Return the todo's worktree path when it exists, else the parent root cwd.

    Grounding and HEAD-anchored diffs must scope to the worktree so they don't
    drift when unrelated deliveries advance parent-root HEAD.
    """
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if worktree_path.is_dir():
        return str(worktree_path)
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


async def prepare_step_prepared(db: Db, slug: str) -> tuple[bool, str]:
    """PREPARED: terminal success state. Emits cleanup for all live slug sessions + self-end."""
    live_sessions = await find_all_live_sessions_for_slug(db, slug)
    return False, format_prepared(slug, session_ids_to_end=live_sessions)

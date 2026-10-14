"""Live todo status map for snippet validation and purge reconciliation.

Reads the todos.db substrate directly (no ORM bootstrap) to resolve which slugs
are live deliverers. Kept in its own module so the snippet validator stays under
the module-size guardrail.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.core.workflow_store.selection import read_workflow_validation_status_rows
from teleclaude.git import GitCommandError, Repo

_TODO_STATUS_VALUES = (
    TodoStatus.ACTIVE,
    TodoStatus.ICEBOX,
    TodoStatus.DELIVERED,
    TodoStatus.REMOVED,
)
_TODO_STATUS_PRIORITY = {
    TodoStatus.REMOVED: -1,
    TodoStatus.DELIVERED: 0,
    TodoStatus.ACTIVE: 1,
    TodoStatus.ICEBOX: 1,
}
_REV_PARSE_VERIFY = "--verify"
_REV_PARSE_QUIET = "--quiet"
_COMMIT_REVISION_SUFFIX = "^{commit}"


@dataclass(frozen=True)
class TodoStatusFact:
    """Validation-relevant state for one todo slug."""

    status: TodoStatus
    delivered_commit: str | None


def build_todo_status_facts(project_root: Path) -> dict[str, TodoStatusFact]:
    """Read todo facts once for checkout-aware snippet validation.

    Falls back to the canonical state root (main repo) when invoked from a
    git worktree where ``.teleclaude/todos.db`` is not present. On a DB that
    still predates the substrate rename, reads the legacy ``roadmap`` table.
    """
    rows = read_workflow_validation_status_rows(project_root)
    if rows is None:
        return {}

    facts: dict[str, TodoStatusFact] = {}
    for slug, raw_status, raw_delivered_commit in rows:
        try:
            status = TodoStatus(raw_status)
        except ValueError:
            continue
        if status not in _TODO_STATUS_VALUES:
            continue
        delivered_commit = raw_delivered_commit
        current = facts.get(slug)
        if current is None or _TODO_STATUS_PRIORITY[status] > _TODO_STATUS_PRIORITY[current.status]:
            facts[slug] = TodoStatusFact(status=status, delivered_commit=delivered_commit)
    return facts


def build_todo_status_map(project_root: Path) -> dict[str, str]:
    """Read todo slug status once for reconciliation consumers."""
    return {slug: fact.status.value for slug, fact in build_todo_status_facts(project_root).items()}


def is_pending_marker_stale(
    slug: str,
    todo_status_facts: Mapping[str, TodoStatusFact],
    project_root: Path,
) -> bool:
    """Return whether a delivered marker should already be folded in this checkout."""
    fact = todo_status_facts.get(slug)
    if fact is None or fact.status is not TodoStatus.DELIVERED or fact.delivered_commit is None:
        return False
    repository = Repo(project_root)
    try:
        repository.git.rev_parse(_REV_PARSE_VERIFY, _REV_PARSE_QUIET, fact.delivered_commit + _COMMIT_REVISION_SUFFIX)
    except GitCommandError as exc:
        if exc.status == 1:
            return False
        raise
    delivered_commit = repository.commit(fact.delivered_commit)
    return repository.is_ancestor(delivered_commit, repository.head.commit)

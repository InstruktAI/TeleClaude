"""Receipt-backed todo filing: the persisted filing request, its project's acceptance order, and its execution.

A filing's request answers its own checks and is accepted with a receipt; the creation transaction, plan seeding
and the todo-created event run here, after the response
(``local/projects/teleclaude/spec/feature/workflow/todo-creation``, Filing under a receipt).
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from instrukt_ai_logging import get_logger
from pydantic import ConfigDict

import teleclaude.core.todo_dependency_warnings as dependency_warnings
from teleclaude.closed_model import ClosedModel
from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.next_machine.todo_creation import NewTodo, announce_todo_created, write_new_todo
from teleclaude.core.next_machine.todo_creation_seeding import seed_plan_drafting, seed_task_plan_authorization
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.types.creation_record import EntryPoint, Lineage
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TodoKind

if TYPE_CHECKING:
    from teleclaude.core.operations.service import OperationsService, SerializedOperation

logger = get_logger(__name__)

# A filing waits on its project's earlier filings by notification; a re-read on this interval covers an earlier
# filing that ended without passing through this process's order, such as one staled at startup.
_ORDER_RECHECK_S: Final = 5.0
_CREATED_TEMPLATE: Final = "Created todo: {slug} (kind={kind})"
_DISPATCHED_NOTICE: Final = (
    "Dispatched to the coordinator. Do not offer, ask about, or narrate further action on this todo."
)
_RESULT_SEPARATOR: Final = "\n"
_TODO_UPDATED_SIGNAL: Final = "todo_updated"
_FILING_COMPLETED_EVENT: Final = "todo creation completed"
_OPERATION_CWD_REQUIRED: Final = "todo filing operation requires its project root"
_TASK_SEED_SESSION_REQUIRED: Final = "a task filing with a supplied task-plan requires its filing session"
_LIFECYCLE_PHASE_FIELD: Final = "lifecycle_phase"


class FilingSeed(StrEnum):
    """What a filing's supplied content seeds beyond its first artifact."""

    NONE = "none"
    IMPLEMENTATION_PLAN = "implementation_plan"
    TASK_PLAN = "task_plan"


class TodoFiling(ClosedModel):
    """One accepted filing request, persisted as its operation's payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str
    kind: TodoKind
    state: dict[str, StateValue]
    lineage: str
    entry_point: EntryPoint | None
    human_involved: bool
    cwd: str
    artifact_name: str
    artifact_body: str
    session_id: str | None
    after: list[str] | None = None
    schedule: str | None = None
    group: str | None = None
    icebox: bool = False
    context: str | None = None
    seed: FilingSeed = FilingSeed.NONE
    pickup_requested: bool

    @classmethod
    def of(cls, new: NewTodo, *, seed: FilingSeed, pickup_requested: bool) -> TodoFiling:
        """The persisted form of a creation the request has fully stated."""
        return cls(
            slug=new.slug,
            kind=new.kind,
            state=new.state,
            lineage=new.lineage.encode(),
            entry_point=new.entry_point,
            human_involved=new.human_involved,
            cwd=new.cwd,
            artifact_name=new.artifact_name,
            artifact_body=new.artifact_body,
            session_id=new.session_id,
            after=new.after,
            schedule=new.schedule,
            group=new.group,
            icebox=new.icebox,
            context=new.context,
            seed=seed,
            pickup_requested=pickup_requested,
        )

    def new_todo(self) -> NewTodo:
        """The creation this filing states; it waits for the git lock as long as other git work holds it."""
        return NewTodo(
            slug=self.slug,
            kind=self.kind,
            state=dict(self.state),
            lineage=Lineage.parse(self.lineage),
            entry_point=self.entry_point,
            human_involved=self.human_involved,
            cwd=self.cwd,
            artifact_name=self.artifact_name,
            artifact_body=self.artifact_body,
            session_id=self.session_id,
            after=self.after,
            schedule=self.schedule,
            group=self.group,
            icebox=self.icebox,
            context=self.context,
        )


class FilingOrder:
    """Holds each filing until every filing its project accepted before it has ended."""

    def __init__(self) -> None:
        self._changed: dict[str, asyncio.Condition] = {}
        self._ended: dict[str, set[str]] = {}

    async def wait_turn(self, db: Db, operation: Operation, project_root: str) -> None:
        """Return once no earlier filing of ``project_root`` is still queued or running."""
        changed = self._changed.setdefault(project_root, asyncio.Condition())
        ended = self._ended.setdefault(project_root, set())
        async with changed:
            while True:
                earlier = await db.earlier_nonterminal_operation_ids(
                    kind=OperationKind.TODO_FILING,
                    cwd=project_root,
                    created_at=operation.created_at,
                    operation_id=operation.operation_id,
                )
                ended.intersection_update(earlier)
                if not set(earlier) - ended:
                    return
                try:
                    await asyncio.wait_for(changed.wait(), timeout=_ORDER_RECHECK_S)
                except TimeoutError:
                    continue

    async def end(self, operation_id: str, project_root: str) -> None:
        """Record that a filing has ended here and wake the filings waiting behind it."""
        changed = self._changed.setdefault(project_root, asyncio.Condition())
        async with changed:
            self._ended.setdefault(project_root, set()).add(operation_id)
            changed.notify_all()


async def submit_todo_filing(
    service: OperationsService,
    *,
    filing: TodoFiling,
    project_root: str,
    caller_session_id: str | None,
    client_request_id: str | None,
) -> SerializedOperation:
    """Accept one filing with a receipt; a repeat of the same request returns the receipt it already has."""
    payload_json = filing.model_dump_json()
    return await service._submit_operation(
        kind=OperationKind.TODO_FILING,
        caller_session_id=caller_session_id,
        cwd=project_root,
        slug=filing.slug,
        client_request_id=client_request_id,
        payload_json=payload_json,
        existing_match_ok=lambda existing: existing.payload_json == payload_json,
    )


async def run_todo_filing_operation(db: Db, operation: Operation, order: FilingOrder) -> str:
    """File one accepted request in its project's acceptance order and report the created todo."""
    project_root = operation.cwd
    if project_root is None:
        raise RuntimeError(_OPERATION_CWD_REQUIRED)
    filing = TodoFiling.model_validate_json(operation.payload_json)
    try:
        await order.wait_turn(db, operation, project_root)
        return await _file(filing, project_root)
    finally:
        await order.end(operation.operation_id, project_root)


async def _file(filing: TodoFiling, project_root: str) -> str:
    new_todo = filing.new_todo()
    todos_db = await get_workflow_store(resolve_project_root(project_root))
    created_identity = await write_new_todo(todos_db, new_todo)
    lifecycle_phase = new_todo.state.get(_LIFECYCLE_PHASE_FIELD)
    if filing.seed is FilingSeed.IMPLEMENTATION_PLAN:
        # The seed runs after the creation's provenance sync, which would otherwise clear it.
        lifecycle_phase = await seed_plan_drafting(todos_db, created_identity, repo_root=new_todo.cwd)
        todos_db.notify_committed(_TODO_UPDATED_SIGNAL)
    elif filing.seed is FilingSeed.TASK_PLAN:
        if new_todo.session_id is None:
            raise RuntimeError(_TASK_SEED_SESSION_REQUIRED)
        lifecycle_phase = await seed_task_plan_authorization(
            todos_db,
            created_identity,
            caller_session_id=new_todo.session_id,
            prepared_session_id=new_todo.session_id,
        )
        todos_db.notify_committed(_TODO_UPDATED_SIGNAL)
    await announce_todo_created(
        new_todo,
        identity=created_identity,
        lifecycle_phase=lifecycle_phase if isinstance(lifecycle_phase, str) else None,
        pickup_requested=filing.pickup_requested,
    )
    logger.info(
        _FILING_COMPLETED_EVENT,
        slug=created_identity,
        kind=filing.kind,
        cwd=new_todo.cwd,
        artifact=new_todo.artifact_name,
    )
    lines = [_CREATED_TEMPLATE.format(slug=created_identity, kind=filing.kind)]
    if filing.pickup_requested:
        lines.append(_DISPATCHED_NOTICE)
    if not filing.icebox and filing.after:
        lines.extend(
            dependency_warnings.frozen_dep_warnings(
                created_identity, await todos_db.get_deps_with_status(created_identity)
            )
        )
    return _RESULT_SEPARATOR.join(lines)

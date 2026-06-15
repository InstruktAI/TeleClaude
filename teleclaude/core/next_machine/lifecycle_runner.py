"""State-derived lifecycle runner dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Unpack

from instrukt_ai_logging import get_logger

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.cli.api_client import RunSessionArgs, TelecAPIClient
from teleclaude.config import config
from teleclaude.core.db import Db, get_db
from teleclaude.core.next_machine.dispatch_claims import (
    acquire_dispatch_claim,
    list_dispatch_claims,
    release_dispatch_claim,
)
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_CHANGE, KIND_FEATURE, KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lifecycle import (
    coerce_lifecycle_phase,
    lifecycle_phase_index,
    pending_approval_gate,
)
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import TodosDb, get_todos_db
from teleclaude.core.todos_db._rows import RoadmapRow
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue

logger = get_logger(__name__)

_ADDITIONAL_CONTEXT = "human_in_loop: false\n"


class RunnerLane(StrEnum):
    ANALYZE = "analyze"
    PREPARE = "prepare"
    WORK = "work"


class RunnerSkipReason(StrEnum):
    ALREADY_DRIVEN = "already-driven"
    APPROVAL_PENDING = "approval-pending"
    AT_CAPACITY = "at-capacity"
    CLAIMED = "claim-conflict"
    DELIVERED = "delivered"
    DEPENDENCY_BLOCKED = "dependency-blocked"
    FINALIZE_READY = "finalize-ready"
    HELD = "held"
    ICEBOX = "icebox"
    INVALID_KIND = "invalid-kind"
    MISSING_STATE = "missing-state"
    POLICY_DISABLED = "policy-disabled"
    REMOVED = "removed"
    TASK_AUTHORIZATION_MISSING = "task-authorization-missing"
    UNKNOWN_PHASE = "unknown-phase"


@dataclass(frozen=True)
class RunnerTodo:
    slug: str
    status: str
    kind: str | None
    lifecycle_phase: str | None
    hold: bool
    active_runner: str | None
    after: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchIntent:
    slug: str
    lane: RunnerLane
    command: str
    thinking_mode: str | None
    additional_context: str


@dataclass
class RunnerDecision:
    evaluated: int = 0
    intents: list[DispatchIntent] = field(default_factory=list)
    skips: dict[RunnerSkipReason, list[str]] = field(default_factory=dict)

    def skip(self, reason: RunnerSkipReason, slug: str) -> None:
        self.skips.setdefault(reason, []).append(slug)


@dataclass
class RunnerResult:
    project_path: str
    trigger: str
    evaluated: int
    dispatched: list[DispatchIntent]
    skips: dict[RunnerSkipReason, list[str]]
    reconciled: list[str]


class SessionRunner(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO: ...


def default_session_runner() -> SessionRunner:
    return TelecAPIClient()


def _dependency_first_order(todos: Mapping[str, RunnerTodo]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(slug: str) -> None:
        if slug in seen:
            return
        if slug in visiting:
            return
        visiting.add(slug)
        todo = todos.get(slug)
        if todo is not None:
            for dep in todo.after:
                if dep in todos:
                    visit(dep)
        visiting.remove(slug)
        seen.add(slug)
        ordered.append(slug)

    for slug in todos:
        visit(slug)
    return ordered


def _command_for_lane(lane: RunnerLane) -> tuple[str, str | None, str]:
    if lane is RunnerLane.ANALYZE:
        return "/analyze-todo-input", None, _ADDITIONAL_CONTEXT
    if lane is RunnerLane.WORK:
        return "/next-work", "med", ""
    return "/next-prepare", "slow", _ADDITIONAL_CONTEXT


def _intent(slug: str, lane: RunnerLane) -> DispatchIntent:
    command, thinking_mode, additional_context = _command_for_lane(lane)
    return DispatchIntent(
        slug=slug,
        lane=lane,
        command=command,
        thinking_mode=thinking_mode,
        additional_context=additional_context,
    )


def _autostart_enabled(kind: str, autostart: Mapping[str, bool]) -> bool:
    return bool(autostart.get(kind, False))


def _pending_approval_gate_for_runner(todo: RunnerTodo) -> bool:
    return (
        pending_approval_gate(
            {
                "kind": todo.kind,
                "lifecycle_phase": todo.lifecycle_phase,
            }
        )
        is not None
    )


def _resolve_kinded_dispatch(
    todo: RunnerTodo,
    kind: str,
    *,
    prepared_slugs: set[str],
    delivered_slugs: set[str],
    autostart: Mapping[str, bool],
) -> tuple[RunnerLane | None, RunnerSkipReason | None]:
    """Resolve the dispatch lane (or skip reason) for a kinded todo."""
    if kind == KIND_TASK:
        if not _autostart_enabled(kind, autostart):
            return None, RunnerSkipReason.POLICY_DISABLED
        return None, RunnerSkipReason.TASK_AUTHORIZATION_MISSING
    if kind not in {KIND_FEATURE, KIND_CHANGE, KIND_BUG}:
        return None, RunnerSkipReason.INVALID_KIND
    if not _autostart_enabled(kind, autostart):
        return None, RunnerSkipReason.POLICY_DISABLED
    phase = coerce_lifecycle_phase(todo.lifecycle_phase)
    if phase is None:
        return None, RunnerSkipReason.UNKNOWN_PHASE
    if phase == LifecyclePhase.FINALIZE_READY:
        return None, RunnerSkipReason.FINALIZE_READY
    if lifecycle_phase_index(phase) >= lifecycle_phase_index(LifecyclePhase.PREPARED):
        unmet = [dep for dep in todo.after if dep not in delivered_slugs]
        lane = RunnerLane.WORK
    else:
        unmet = [dep for dep in todo.after if dep not in prepared_slugs]
        lane = RunnerLane.PREPARE
    if unmet:
        return None, RunnerSkipReason.DEPENDENCY_BLOCKED
    return lane, None


def decide_dispatches(
    todos: Mapping[str, RunnerTodo],
    *,
    prepared_slugs: set[str],
    delivered_slugs: set[str],
    autostart: Mapping[str, bool],
    live_session_ids: set[str],
    claimed: set[tuple[str, RunnerLane]] | None = None,
    max_dispatch: int = 5,
    live_driver_count: int = 0,
) -> RunnerDecision:
    decision = RunnerDecision(evaluated=len(todos))
    active_claims = claimed or set()
    any_autostart = any(autostart.values())
    # Concurrency budget: how many more drivers may go live this pass. Each
    # dispatched intent consumes one slot on top of the already-live drivers.
    # TODO: exclude manually_started drivers from the live count — that exclusion
    # lands in a later track; for now all live drivers count toward the cap.
    remaining_budget = max(0, max_dispatch - live_driver_count)

    def _at_capacity() -> bool:
        return remaining_budget - len(decision.intents) <= 0

    for slug in _dependency_first_order(todos):
        todo = todos[slug]
        if todo.status == "removed":
            decision.skip(RunnerSkipReason.REMOVED, slug)
            continue
        if todo.status == "delivered":
            decision.skip(RunnerSkipReason.DELIVERED, slug)
            continue
        if todo.status == "icebox":
            decision.skip(RunnerSkipReason.ICEBOX, slug)
            continue
        # Approval-pending and held are independent skips with no precedence.
        if _pending_approval_gate_for_runner(todo):
            decision.skip(RunnerSkipReason.APPROVAL_PENDING, slug)
            continue
        if todo.hold:
            decision.skip(RunnerSkipReason.HELD, slug)
            continue
        if todo.active_runner and todo.active_runner in live_session_ids:
            decision.skip(RunnerSkipReason.ALREADY_DRIVEN, slug)
            continue
        if todo.kind is None:
            lane = RunnerLane.ANALYZE
            if not any_autostart:
                decision.skip(RunnerSkipReason.POLICY_DISABLED, slug)
                continue
            if (slug, lane) in active_claims:
                decision.skip(RunnerSkipReason.CLAIMED, slug)
                continue
            if _at_capacity():
                decision.skip(RunnerSkipReason.AT_CAPACITY, slug)
                continue
            decision.intents.append(_intent(slug, lane))
            continue
        try:
            kind = canonical_kind(todo.kind)
        except ValueError:
            decision.skip(RunnerSkipReason.INVALID_KIND, slug)
            continue
        lane, skip_reason = _resolve_kinded_dispatch(
            todo,
            kind,
            prepared_slugs=prepared_slugs,
            delivered_slugs=delivered_slugs,
            autostart=autostart,
        )
        if lane is None:
            decision.skip(skip_reason or RunnerSkipReason.INVALID_KIND, slug)
            continue
        if (slug, lane) in active_claims:
            decision.skip(RunnerSkipReason.CLAIMED, slug)
            continue
        if _at_capacity():
            decision.skip(RunnerSkipReason.AT_CAPACITY, slug)
            continue
        decision.intents.append(_intent(slug, lane))
    return decision


async def _is_live_runner(db: Db, session_id: str | None) -> bool:
    return bool(session_id and await is_live_session_id(db, session_id))


async def _read_runner_todo(todos_db: TodosDb, row: RoadmapRow) -> RunnerTodo | None:
    if row["status"] in {"delivered", "removed"}:
        return RunnerTodo(
            slug=row["slug"],
            status=row["status"],
            kind=None,
            lifecycle_phase=None,
            hold=False,
            active_runner=None,
            after=(),
        )
    state = await todos_db.read_state(row["slug"])
    if state is None:
        return None
    return _todo_from_state(row, state)


def _todo_from_state(row: RoadmapRow, state: Mapping[str, StateValue]) -> RunnerTodo:
    kind = state.get("kind")
    phase = state.get("lifecycle_phase")
    active_runner = state.get("active_runner")
    return RunnerTodo(
        slug=row["slug"],
        status=row["status"],
        kind=kind if isinstance(kind, str) else None,
        lifecycle_phase=phase if isinstance(phase, str) else None,
        hold=state.get("hold") is True,
        active_runner=active_runner if isinstance(active_runner, str) and active_runner else None,
        after=(),
    )


async def _clear_active_runner(todos_db: TodosDb, slug: str) -> None:
    state = await todos_db.read_state(slug)
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = None
    await writer.commit(todos_db, slug)


async def _set_active_runner(todos_db: TodosDb, slug: str, session_id: str) -> None:
    state = await todos_db.read_state(slug)
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = session_id
    await writer.commit(todos_db, slug)


async def _load_todos(
    todos_db: TodosDb, db: Db, *, claimed_slugs: set[str] | None = None
) -> tuple[dict[str, RunnerTodo], list[str]]:
    rows = await todos_db.list_roadmap(include_icebox=True, include_delivered=True, include_removed=True)
    deps = await todos_db.load_deps()
    outstanding = claimed_slugs or set()
    loaded: dict[str, RunnerTodo] = {}
    reconciled: list[str] = []
    for row in rows:
        todo = await _read_runner_todo(todos_db, row)
        if todo is None:
            loaded[row["slug"]] = RunnerTodo(
                slug=row["slug"],
                status=row["status"],
                kind=None,
                lifecycle_phase=None,
                hold=False,
                active_runner=None,
            )
            continue
        todo = RunnerTodo(
            slug=todo.slug,
            status=todo.status,
            kind=todo.kind,
            lifecycle_phase=todo.lifecycle_phase,
            hold=todo.hold,
            active_runner=todo.active_runner,
            after=tuple(deps.get(todo.slug, [])),
        )
        # Do not reconcile-clear a slug whose dispatch claim is still outstanding:
        # the spawn->live boot window is bridged by the claim lease, and the
        # session row may not yet read as live. Clearing here would race the next
        # pass into a duplicate dispatch (the storm this guard prevents).
        if todo.active_runner and todo.slug not in outstanding and not await _is_live_runner(db, todo.active_runner):
            await _clear_active_runner(todos_db, todo.slug)
            reconciled.append(todo.slug)
            todo = RunnerTodo(
                slug=todo.slug,
                status=todo.status,
                kind=todo.kind,
                lifecycle_phase=todo.lifecycle_phase,
                hold=todo.hold,
                active_runner=None,
                after=todo.after,
            )
        loaded[todo.slug] = todo
    return loaded, reconciled


async def _live_active_runners(db: Db, todos: Mapping[str, RunnerTodo]) -> set[str]:
    live: set[str] = set()
    for todo in todos.values():
        if todo.active_runner and await _is_live_runner(db, todo.active_runner):
            live.add(todo.active_runner)
    return live


async def _run_intent(
    *,
    client: SessionRunner,
    todos_db: TodosDb,
    project_path: str,
    intent: DispatchIntent,
) -> str | None:
    owner = f"lifecycle-runner:{intent.command}:{intent.slug}"
    acquired = await acquire_dispatch_claim(todos_db, slug=intent.slug, lane=intent.lane.value, owner=owner)
    if not acquired:
        return None
    try:
        kwargs: RunSessionArgs = {
            "command": intent.command,
            "project_path": project_path,
            "args": intent.slug,
            "detach": True,
        }
        if intent.thinking_mode is not None:
            kwargs["thinking_mode"] = intent.thinking_mode
        if intent.additional_context:
            kwargs["additional_context"] = intent.additional_context
        response = await client.run_session(**kwargs)
    except BaseException:
        # Spawn failed: drop the claim so a later pass can retry. On success the
        # claim is intentionally retained — its lease bridges the spawn->live gap
        # so the next pass sees the live active_runner and skips ALREADY_DRIVEN.
        await release_dispatch_claim(todos_db, slug=intent.slug, lane=intent.lane.value, owner=owner)
        raise
    await _set_active_runner(todos_db, intent.slug, response.session_id)
    return response.session_id


async def run_lifecycle_runner(
    project_path: str | Path,
    *,
    trigger: str = "manual",
    db: Db | None = None,
    client_factory: Callable[[], SessionRunner] = default_session_runner,
) -> RunnerResult:
    project_root = Path(project_path).resolve()
    runtime_db = db or await get_db()
    todos_db = await get_todos_db(project_root)
    claims = await list_dispatch_claims(todos_db)
    claimed_pairs = {(claim.slug, RunnerLane(claim.lane)) for claim in claims}
    claimed_slugs = {claim.slug for claim in claims}
    todos, reconciled = await _load_todos(todos_db, runtime_db, claimed_slugs=claimed_slugs)
    prepared_slugs = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered_slugs = await effective_delivered_slugs_for_dependencies(todos_db)
    workflow = config.workflow
    autostart = {
        KIND_FEATURE: workflow.autostart.feature,
        KIND_CHANGE: workflow.autostart.change,
        KIND_BUG: workflow.autostart.bug,
        KIND_TASK: workflow.autostart.task,
    }
    live_session_ids = await _live_active_runners(runtime_db, todos)
    decision = decide_dispatches(
        todos,
        prepared_slugs=prepared_slugs,
        delivered_slugs=delivered_slugs,
        autostart=autostart,
        live_session_ids=live_session_ids,
        claimed=claimed_pairs,
        max_dispatch=workflow.max_todo_dispatch,
        live_driver_count=len(live_session_ids),
    )

    dispatched: list[DispatchIntent] = []
    client = client_factory()
    await client.connect()
    try:
        for intent in decision.intents:
            session_id = await _run_intent(
                client=client, todos_db=todos_db, project_path=str(project_root), intent=intent
            )
            if session_id is None:
                decision.skip(RunnerSkipReason.CLAIMED, intent.slug)
                continue
            dispatched.append(intent)
    finally:
        await client.close()

    result = RunnerResult(
        project_path=str(project_root),
        trigger=trigger,
        evaluated=decision.evaluated,
        dispatched=dispatched,
        skips=decision.skips,
        reconciled=reconciled,
    )
    logger.info(
        "lifecycle runner pass",
        project_path=result.project_path,
        trigger=trigger,
        evaluated=result.evaluated,
        dispatched=[(intent.slug, intent.lane.value) for intent in dispatched],
        skips={reason.value: slugs for reason, slugs in result.skips.items()},
        reconciled=reconciled,
    )
    return result


def project_path_from_event_payload(payload: Mapping[str, object]) -> str | None:
    project_path = payload.get("project_path")
    if isinstance(project_path, str) and project_path:
        return project_path
    return None


__all__ = [
    "DispatchIntent",
    "RunnerDecision",
    "RunnerLane",
    "RunnerResult",
    "RunnerSkipReason",
    "RunnerTodo",
    "decide_dispatches",
    "default_session_runner",
    "project_path_from_event_payload",
    "run_lifecycle_runner",
]

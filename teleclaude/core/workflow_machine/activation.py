"""Store activation: classify every item row, convert the legacy ones, normalize the complete ones, record the mark.

``local/projects/teleclaude/design/architecture/workflow-store`` (Activation) and
``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Conversion, Complete legacy records are normalized
forward, Admission at activation). The store owns the transaction (``run_activation``); this module owns what each row
becomes. The classification is a pure function of the row, the integrator's checkpoint read inside the transaction and
the integration heads read before it, so a verification pass can ask it again and expect nothing left to convert.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.integration.checkpoint import (
    CHECKPOINT_STATE_FILENAME,
    IntegrationPhase,
    _default_state_dir,
    _upcast_checkpoint_payload,
)
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.create import creative_incomplete_observed
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.workflow_machine.heads import observed_head
from teleclaude.core.workflow_machine.phase_reading import TASK_LANE_STORED_PHASES, stored_in_legacy_phase
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ActivationRefused, ActivationRow, ConversionPath, RowRewrite
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import LIFECYCLE_PHASE_STATE_KEY, FinalizeStatus, TodoState
from teleclaude.types.workflow_record import (
    AdmittedCandidate,
    CreativeEpisode,
    EpisodePath,
    StampRecord,
    StampSource,
    WorkflowRecord,
)

logger = get_logger(__name__)

NO_SESSION: Final = ""
UNREADABLE_CHECKPOINT: Final = (
    "the integrator's checkpoint cannot be read, so no row is converted; recover it with `telec todo integrate`"
)
ADMISSION_CONFLICT: Final = (
    "{item} records an admission at {recorded} but the integrator's checkpoint names {named}; "
    "the store is not activated until `telec todo integrate` settles the attempt"
)
LEFT_TO_CONVERT: Final = "{item} is still stored in the legacy phase {phase} after the pass"
INVALID_STATE: Final = "{item}: its stored state cannot be read ({reason})"
ACTIVATION_DONE_LOG: Final = "workflow store activated"
ACTIVATION_FAILED_LOG: Final = "workflow store activation failed; the store stays unmarked"
CONVERGED_LOG: Final = "workflow store converged deferred rows"
SHORT_SHA: Final = 8
INACTIVE_PHASES: Final = frozenset({IntegrationPhase.IDLE.value, IntegrationPhase.COMPLETED.value})


ClassifyFn = Callable[[list[ActivationRow]], list[RowRewrite]]
VerifyFn = Callable[[list[ActivationRow]], None]


@dataclass(frozen=True)
class ActiveCandidate:
    """The identity the integrator's checkpoint names while an attempt is dequeued, in progress or committed."""

    slug: str
    branch: str
    sha: str


@dataclass(frozen=True)
class ActivationFacts:
    """What the classification reads besides the row: the checkpoint, the integration heads and the time."""

    project_root: str
    candidate: ActiveCandidate | None
    heads: Mapping[str, str | None]
    now: str


def read_checkpoint_strictly(project_root: str) -> ActiveCandidate | None:
    """The active attempt the checkpoint names, or None; an unreadable checkpoint is a refusal, not an idle one.

    A queued or parked entry is not an attempt: only a candidate in a phase other than idle or completed counts.
    """
    path = Path(_default_state_dir(project_root)) / CHECKPOINT_STATE_FILENAME
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        data = _upcast_checkpoint_payload(json.loads(raw))
    except (OSError, TypeError, ValueError) as failure:
        raise ActivationRefused(UNREADABLE_CHECKPOINT) from failure
    slug, branch, sha = data.get("candidate_slug"), data.get("candidate_branch"), data.get("candidate_sha")
    if data.get("phase", IntegrationPhase.IDLE.value) in INACTIVE_PHASES or not (slug and branch and sha):
        return None
    return ActiveCandidate(slug=str(slug), branch=str(branch), sha=str(sha))


def _rewrite(row: ActivationRow, record: WorkflowRecord, phase: LifecyclePhase | None) -> dict[str, StateValue]:
    """The row's state with the new workflow record and, when given, the new stored phase; nothing else changes."""
    new_state: dict[str, StateValue] = dict(row.state)
    new_state[WORKFLOW_STATE_KEY] = record.to_state()
    if phase is not None:
        new_state[LIFECYCLE_PHASE_STATE_KEY] = phase.value
    return new_state


def _admission_of(
    row: ActivationRow, record: WorkflowRecord, facts: ActivationFacts
) -> tuple[AdmittedCandidate | None, bool]:
    """The row's admission: the recorded one, or the one the checkpoint's active candidate establishes from its identity."""
    candidate = facts.candidate
    named = candidate if candidate is not None and candidate.slug == row.slug else None
    recorded = record.admitted
    if recorded is not None:
        if named is not None and (recorded.branch, recorded.sha) != (named.branch, named.sha):
            raise ActivationRefused(
                ADMISSION_CONFLICT.format(
                    item=row.slug,
                    recorded=recorded.sha[:SHORT_SHA],
                    named=f"{named.branch}@{named.sha[:SHORT_SHA]}",
                )
            )
        return recorded, False
    if named is not None:
        return AdmittedCandidate(branch=named.branch, sha=named.sha, at=facts.now, session_id=NO_SESSION), True
    return None, False


def _creative_incomplete(row: ActivationRow, facts: ActivationFacts) -> bool:
    return creative_incomplete_observed(
        facts.project_root,
        row.slug,
        row.state,
        has_input=row.has_input,
        has_design_spec=row.has_design_spec,
    )


def _classify_admitted(
    row: ActivationRow, state: TodoState, admission: AdmittedCandidate, backfilled: bool, facts: ActivationFacts
) -> RowRewrite | None:
    """An admitted row keeps its phase and holder; a legacy one with an incomplete design records a deferred episode."""
    record = state.workflow.model_copy(deep=True)
    changed = backfilled
    if backfilled:
        record.admitted = admission
    if stored_in_legacy_phase(state) and record.episode is None and _creative_incomplete(row, facts):
        record.episode = CreativeEpisode(opened_at=facts.now, path=EpisodePath.CONVERSION, deferred=True)
        changed = True
    if not changed:
        return None
    return RowRewrite(row_id=row.row_id, state=_rewrite(row, record, None))


def _normalized_phase(
    row: ActivationRow, state: TodoState, facts: ActivationFacts
) -> tuple[LifecyclePhase, StampRecord | None] | None:
    """The phase a complete legacy record is normalized to and its carried stamp; None when its head cannot be read."""
    stored = state.lifecycle_phase
    drift = state.plan_review.cleared_by_substantive_drift
    if stored is LifecyclePhase.FINALIZE_READY:
        finalize = state.finalize
        if finalize.status is FinalizeStatus.READY and finalize.sha and not drift:
            stamp = StampRecord(
                sha=finalize.sha,
                session_id=NO_SESSION,
                ready_at=finalize.ready_at or facts.now,
                source=StampSource.CARRIED_HANDOFF,
            )
            return LifecyclePhase.READY, stamp
    if stored is LifecyclePhase.REVIEW_APPROVED and state.build_review.reviewed_target_digest:
        head = facts.heads.get(row.slug)
        if head is None:
            return None
        reviewed = state.build_review.reviewed_target_digest
        if head and head == reviewed and not drift:
            stamp = StampRecord(
                sha=reviewed,
                session_id=NO_SESSION,
                ready_at=state.build_review.reviewed_at or facts.now,
                source=StampSource.CARRIED_VERDICT,
            )
            return LifecyclePhase.READY, stamp
    return LifecyclePhase.PREPARATION, None


def _classify_legacy(row: ActivationRow, state: TodoState, facts: ActivationFacts) -> RowRewrite | None:
    """A legacy record with no admission: convert it, complete its deferred conversion, or normalize it forward."""
    record = state.workflow.model_copy(deep=True)
    stored = state.lifecycle_phase.value
    episode = record.episode
    if episode is not None or _creative_incomplete(row, facts):
        if episode is None:
            record.episode = CreativeEpisode(opened_at=facts.now, path=EpisodePath.CONVERSION)
        elif episode.deferred:
            record.episode = episode.model_copy(update={"deferred": False})
        return RowRewrite(
            row_id=row.row_id,
            state=_rewrite(row, record, LifecyclePhase.PREPARATION),
            converted_from=stored,
            path=ConversionPath.ACTIVATION,
        )
    normalized = _normalized_phase(row, state, facts)
    if normalized is None:
        return None
    phase, stamp = normalized
    record.stamp = stamp
    return RowRewrite(
        row_id=row.row_id,
        state=_rewrite(row, record, phase),
        converted_from=stored,
        path=ConversionPath.ACTIVATION,
    )


def classify_row(row: ActivationRow, facts: ActivationFacts) -> RowRewrite | None:
    """What the activation writes for one row, or None when the row needs nothing now."""
    try:
        state = TodoState.model_validate(row.state)
    except ValueError as failure:
        raise ActivationRefused(INVALID_STATE.format(reason=str(failure).splitlines()[0], item=row.slug)) from failure
    stored = state.lifecycle_phase
    if (
        state.kind == KIND_TASK
        or stored in TASK_LANE_STORED_PHASES
        or stored is LifecyclePhase.DELIVERED
        or row.converted
    ):
        return None
    admission, backfilled = _admission_of(row, state.workflow, facts)
    if admission is not None:
        return _classify_admitted(row, state, admission, backfilled, facts)
    if not stored_in_legacy_phase(state):
        return None
    return _classify_legacy(row, state, facts)


class _InTransaction:
    """The facts of one pass, with the checkpoint read at the moment the transaction classifies, never before it."""

    def __init__(self, facts: ActivationFacts) -> None:
        self._facts = facts
        self.facts = facts

    def classify(self, rows: list[ActivationRow]) -> list[RowRewrite]:
        """The rewrites for the rows, under the checkpoint as it is now."""
        self.facts = replace(self._facts, candidate=read_checkpoint_strictly(self._facts.project_root))
        return [rewrite for row in rows if (rewrite := classify_row(row, self.facts)) is not None]

    def verify(self, rows: list[ActivationRow]) -> None:
        """Nothing may be left to convert once the rewrites have been applied."""
        for row in rows:
            if classify_row(row, self.facts) is not None:
                phase = str(row.state.get(LIFECYCLE_PHASE_STATE_KEY))
                raise ActivationRefused(LEFT_TO_CONVERT.format(item=row.slug, phase=phase))


async def _prefetch_heads(store: WorkflowStore, project_root: str) -> dict[str, str | None]:
    """The integration heads of the legacy review verdicts, read before the transaction; None when a read failed."""
    heads: dict[str, str | None] = {}
    for slug in await store.slugs_stored_in_phase(LifecyclePhase.REVIEW_APPROVED.value):
        observed = await observed_head(project_root, slug)
        heads[slug] = None if observed.unreadable else observed.head
    return heads


async def restore_classifier(
    project_root: str, todo_id: str, store: WorkflowStore
) -> Callable[[ActivationRow], RowRewrite | None] | None:
    """The classification a restored row passes through in the restore's own transaction; None for an unmarked store.

    The head is read here, before the restore's transaction, as the activation reads heads; the checkpoint is read
    inside it, when the row is classified, and an unreadable one refuses the restore naming the recovery. A store the
    activation has not marked classifies the row itself when it first runs, so a restore there owes nothing.
    """
    _, marked = await store.read_activation()
    if not marked:
        return None
    raw = await store.read_state_by_id(todo_id)
    slug = await store.slug_for_row_id(todo_id)
    heads: dict[str, str | None] = {}
    if raw is not None and slug and raw.get(LIFECYCLE_PHASE_STATE_KEY) == LifecyclePhase.REVIEW_APPROVED.value:
        observed = await observed_head(project_root, slug)
        heads[slug] = None if observed.unreadable else observed.head
    pass_ = _InTransaction(
        ActivationFacts(project_root=project_root, candidate=None, heads=heads, now=datetime.now(UTC).isoformat())
    )

    def classify(row: ActivationRow) -> RowRewrite | None:
        rewrites = pass_.classify([row])
        return rewrites[0] if rewrites else None

    return classify


async def activate_project(project_root: str) -> None:
    """Activate the project's store if it is unmarked, or converge the deferred rows of a marked one.

    A failure leaves the store unmarked and is raised to the supervising caller, which logs it; every other store
    proceeds.
    """
    store = await get_workflow_store(project_root)
    in_place, marked = await store.read_activation()
    if not in_place:
        raise ActivationRefused("the activation schema is not in place")
    now = datetime.now(UTC).isoformat()
    heads = await _prefetch_heads(store, project_root)
    pass_ = _InTransaction(ActivationFacts(project_root=project_root, candidate=None, heads=heads, now=now))
    changed = await store.run_activation(pass_.classify, pass_.verify, mark=not marked)
    if not marked:
        logger.info(ACTIVATION_DONE_LOG, project_root=project_root, rows_changed=changed)
    elif changed:
        logger.info(CONVERGED_LOG, project_root=project_root, rows_changed=changed)


_LAST_FAILURE: dict[str, str] = {}
NOT_ACTIVATED: Final = "the store of {project} is not activated yet: {cause}"
NOT_ACTIVATED_YET: Final = "the next tick of the daemon activates it"


class StoreNotActivated(Exception):
    """The machine's read, act or scan was refused because the store carries no completion mark."""


async def activate_project_supervised(project_root: str) -> None:
    """Activate one project, containing and logging a failure so every other store proceeds."""
    try:
        await activate_project(project_root)
    except Exception as failure:  # supervision boundary: one store's failure leaves it unmarked, no other store
        _LAST_FAILURE[project_root] = str(failure) or type(failure).__name__
        logger.exception(ACTIVATION_FAILED_LOG, project_root=project_root)
    else:
        _LAST_FAILURE.pop(project_root, None)


async def require_activated(store: WorkflowStore) -> None:
    """Refuse the machine's read, act or scan on a store the activation has not marked, naming the cause.

    The integrator's own entry stays outside this refusal so that the recovery the cause names can run.
    """
    in_place, marked = await store.read_activation()
    if in_place and marked:
        return
    project_root = str(store.project_root)
    cause = _LAST_FAILURE.get(project_root, NOT_ACTIVATED_YET if in_place else "its activation schema is not in place")
    raise StoreNotActivated(NOT_ACTIVATED.format(project=project_root, cause=cause))

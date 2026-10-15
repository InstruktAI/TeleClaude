"""Admitting a candidate: one conditional commit on the item before the integrator's own checkpoint.

``local/projects/teleclaude/spec/integration-orchestrator`` is the contract. The commit rechecks, under the item's
writer lock, that the item still reads ready at the candidate's commit and that the creative lane has not moved since
the scan, then records the admitted commit and the started phase in one write. The checkpoint is written afterwards, so
a crash between the two leaves an admission the next scan recovers into a checkpoint, never a checkpoint for an item
that was not admitted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.integration.candidate_scan import CandidateKey, candidate_is_held
from teleclaude.core.integration.git_ops import _run_git
from teleclaude.core.workflow_machine.lane import resolve_lane_sync
from teleclaude.core.workflow_machine.phase_reading import LaneFacts, creative_snapshot, read_phase
from teleclaude.core.workflow_store.store import get_workflow_store, get_workflow_store_sync
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import AdmittedCandidate, Phase

logger = get_logger(__name__)

RETIRE_FAILED_LOG: Final = "retiring an integration admission failed"
INTEGRATION_PHASE_STATE_KEY: Final = "integration_phase"
STARTED_PHASE: Final = "started"
ADMISSION_TIMEOUT_SECONDS: Final = 30
ORIGIN: Final = "origin"
BRANCH_REF_TEMPLATE: Final = "refs/heads/{branch}"

ItemMutation = Callable[[dict[str, StateValue] | None, Mapping[str, str]], ItemChange | None]


class AdmissionRefusal(StrEnum):
    """Why a candidate was not admitted; the item changed after the scan read it."""

    UNKNOWN_ITEM = "{item} is no longer a known item"
    HELD = "{item} is held or kicked back"
    NOT_READY = "{item} no longer reads ready at {sha}"
    CREATIVE_MOVED = "{item}'s creative design changed after the scan"
    HEAD_UNREADABLE = "the branch of {item} cannot be read on origin"
    HEAD_MOVED = "the branch of {item} moved to {head} after the scan read {sha}"
    OTHER_ADMISSION = "{item} already holds an admission at {sha}"


class AdmissionRefused(Exception):
    """The candidate is not admitted; nothing was written."""


@dataclass(frozen=True)
class Admission:
    """The outcome of an admission: the refusal text when refused, empty when the commit is recorded."""

    refused: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _mutation(key: CandidateKey, lane: LaneFacts, snapshot: str, session_id: str) -> ItemMutation:
    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise AdmissionRefused(AdmissionRefusal.UNKNOWN_ITEM.value.format(item=key.slug))
        state = TodoState.model_validate(current)
        admitted = state.workflow.admitted
        if admitted is not None and admitted.sha == key.sha:
            return None
        if admitted is not None:
            raise AdmissionRefused(AdmissionRefusal.OTHER_ADMISSION.value.format(item=key.slug, sha=admitted.sha[:8]))
        head = lane.integration_head
        if head != key.sha:
            raise AdmissionRefused(
                AdmissionRefusal.HEAD_MOVED.value.format(item=key.slug, head=head[:8], sha=key.sha[:8])
            )
        if creative_snapshot(current) != snapshot:
            raise AdmissionRefused(AdmissionRefusal.CREATIVE_MOVED.value.format(item=key.slug))
        if candidate_is_held(current, state, head):
            raise AdmissionRefused(AdmissionRefusal.HELD.value.format(item=key.slug))
        reading = read_phase(state, lane)
        if reading.phase is not Phase.READY or reading.ready_sha != key.sha:
            raise AdmissionRefused(AdmissionRefusal.NOT_READY.value.format(item=key.slug, sha=key.sha[:8]))
        record = workflow_record_of(current).model_copy(deep=True)
        record.admitted = AdmittedCandidate(branch=key.branch, sha=key.sha, at=_now(), session_id=session_id)
        return ItemChange(
            state={**current, WORKFLOW_STATE_KEY: record.to_state(), INTEGRATION_PHASE_STATE_KEY: STARTED_PHASE}
        )

    return mutate


async def _commit(project_root: str, key: CandidateKey, mutation: ItemMutation, expected: dict[str, str]) -> None:
    store = await get_workflow_store(project_root)
    await store.commit_item_change(key.slug, expect_digests=expected, mutate=mutation, updated_by=None)


def _branch_head(cwd: str, branch: str) -> str:
    rc, stdout, _ = _run_git(["ls-remote", "--exit-code", ORIGIN, BRANCH_REF_TEMPLATE.format(branch=branch)], cwd=cwd)
    parts = stdout.split()
    return parts[0] if rc == 0 and parts else ""


def admit_candidate(cwd: str, key: CandidateKey, session_id: str, loop: asyncio.AbstractEventLoop | None) -> Admission:
    """Commit the admission of one candidate on its item, or report why the item no longer qualifies.

    The creative lane and the branch head are read again here, so the commit decides on state read after the scan; the
    artifacts the lane reads are fenced at the commit by their digests, the creative section by its snapshot.
    """
    store = get_workflow_store_sync(cwd)
    raw = store.read_state_sync(key.slug)
    if raw is None:
        return Admission(AdmissionRefusal.UNKNOWN_ITEM.value.format(item=key.slug))
    admitted = workflow_record_of(raw).admitted
    if admitted is not None:
        if admitted.sha == key.sha:
            return Admission()
        return Admission(AdmissionRefusal.OTHER_ADMISSION.value.format(item=key.slug, sha=admitted.sha[:8]))
    head = _branch_head(cwd, key.branch)
    if not head:
        return Admission(AdmissionRefusal.HEAD_UNREADABLE.value.format(item=key.slug))
    lane = resolve_lane_sync(store, cwd, key.slug, raw, head)
    expected = lane.expected_digests
    if lane.creative_incomplete:
        return Admission(AdmissionRefusal.CREATIVE_MOVED.value.format(item=key.slug))
    mutation = _mutation(key, lane, creative_snapshot(raw), session_id)
    commit = _commit(cwd, key, mutation, expected)
    try:
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(commit, loop).result(timeout=ADMISSION_TIMEOUT_SECONDS)
        else:
            asyncio.run(commit)
    except AdmissionRefused as refusal:
        return Admission(str(refusal))
    return Admission()


def _retirement(key: CandidateKey) -> ItemMutation:
    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current)
        if record.admitted is None or record.admitted.sha != key.sha:
            return None
        updated = record.model_copy(deep=True)
        updated.admitted = None
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    return mutate


def retire_admission(cwd: str, key: CandidateKey, loop: asyncio.AbstractEventLoop | None) -> None:
    """Retire the admission of exactly this commit when the integrator parks it; a failure is logged and retried by the next park."""
    commit = _commit(cwd, key, _retirement(key), {})
    try:
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(commit, loop).result(timeout=ADMISSION_TIMEOUT_SECONDS)
        else:
            asyncio.run(commit)
    except (
        Exception
    ):  # supervision boundary: a failed retirement leaves the admission, which the next drain picks up again
        logger.exception(RETIRE_FAILED_LOG, slug=key.slug)

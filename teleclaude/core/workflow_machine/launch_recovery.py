"""Recovery of a driver start that never reached a claim.

A launch reservation says a driver was requested for an item and has not claimed it. It is cleared when the
driver claims. When the start fails, or the driver ends without claiming, it would otherwise stand forever and
every later entry would wait for a driver that does not exist. The reservation is released only on evidence
that no driver can still arrive: the request event has gone out, the reservation is older than the window a
start is given, and no live session is bound to the item.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY
from teleclaude.types.workflow_record import ActStatus

logger = get_logger(__name__)

LAUNCH_WINDOW_SECONDS: Final = 900
RECOVERY_FAILED_LOG: Final = "launch recovery failed for an item"
RECOVERED_LOG: Final = "launch reservation released without a claim"
RECOVERY_NOTE: Final = (
    "\n### {at} — platform · launch released\n\nNo driver claimed {item} within {window} seconds of the request "
    "and none is running for it; the start request was released.\n"
)


async def _has_live_bound_session(item: str) -> bool:
    """Whether an open session is bound to the item as an agent procedure activation."""
    for session in await db.list_sessions(all_open=True):
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            continue
        binding = (session.origin_metadata or {}).get(BINDING_SECTION)
        if isinstance(binding, dict) and binding.get(BindingField.SUBJECT.value) == item:
            return True
    return False


def _release(item: str, key: str, now: datetime) -> Callable[..., ItemChange | None]:
    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None or current.get(ACTIVE_RUNNER_STATE_KEY):
            return None
        record = workflow_record_of(current)
        if record.launch is None or record.launch.key != key:
            return None
        if any(effect.act_key == key for effect in record.pending_effects):
            return None
        updated = record.model_copy(deep=True)
        updated.launch = None
        updated.act_status[key] = ActStatus.COMPLETE
        note = RECOVERY_NOTE.format(at=now.isoformat(), item=item, window=LAUNCH_WINDOW_SECONDS)
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()}, log_entry=note)

    return mutate


async def _recover_item(store: WorkflowStore, project_root: str, item: str) -> None:
    raw = await store.read_state(item)
    if raw is None or raw.get(ACTIVE_RUNNER_STATE_KEY):
        return
    launch = workflow_record_of(raw).launch
    if launch is None:
        return
    now = datetime.now(UTC)
    if (now - datetime.fromisoformat(launch.requested_at)).total_seconds() < LAUNCH_WINDOW_SECONDS:
        return
    if await _has_live_bound_session(item):
        return
    await store.commit_item_change(item, expect_digests={}, mutate=_release(item, launch.key, now), updated_by=None)
    logger.info(RECOVERED_LOG, slug=item, project_root=project_root, reservation=launch.key)


async def recover_stale_launches_supervised(project_root: str) -> None:
    """Release the stale launch reservations of a project; one failing item stops neither the others nor the project."""
    try:
        store = await get_workflow_store(project_root)
        for entry in await store.list_todo():
            try:
                await _recover_item(store, project_root, entry["slug"])
            except Exception:  # supervision boundary: one unreadable item must not stop the others
                logger.exception(RECOVERY_FAILED_LOG, slug=entry["slug"], project_root=project_root)
    except Exception:  # supervision boundary: one broken project must not starve the others
        logger.exception(RECOVERY_FAILED_LOG, project_root=project_root)

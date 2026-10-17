"""The integrator's periodic scan: a ready item is admitted whether or not its notice was ever raised or consumed.

``local/projects/teleclaude/spec/integration-orchestrator`` is the contract. The ready event prompts the integrator,
but readiness is the item's canonical phase, so a missed or unconsumed event delays admission only until this scan runs
on the next tick of the schedule clock.
"""

from __future__ import annotations

import asyncio
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.integration.candidate_scan import ScannedCandidate, _scan_finalize_ready_candidates
from teleclaude.core.integration.checkpoint import (
    CHECKPOINT_STATE_FILENAME,
    _default_state_dir,
    _read_checkpoint,
    pending_retirements,
)
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.types.claim_change import workflow_record_of

logger = get_logger(__name__)

SCAN_CALLER: Final = "periodic-scan"
SCAN_FAILED_LOG: Final = "the integrator's periodic candidate scan failed"


def _ready_candidates(project_root: str) -> list[ScannedCandidate]:
    """The candidates that are ready now, leaving out the ones the integrator parked."""
    checkpoint = _read_checkpoint(_default_state_dir(project_root) / CHECKPOINT_STATE_FILENAME)
    parked = {parked["slug"] for parked in checkpoint.parked}
    return _scan_finalize_ready_candidates(project_root, parked_slugs=parked, retiring=pending_retirements(checkpoint))


async def ensure_integrator_for_ready_items(project_root: str) -> None:
    """Start the project's integrator when an item is ready and none is running; contained so a pass never fails."""
    from teleclaude.core.integration_bridge import spawn_integrator_session  # noqa: PLC0415 - deferred cycle

    try:
        candidates = await asyncio.to_thread(_ready_candidates, project_root)
        if not candidates:
            return
        first = candidates[0].key
        store = await get_workflow_store(project_root)
        raw = await store.read_state(first.slug)
        stamp = workflow_record_of(raw).stamp if raw is not None else None
        caller = stamp.session_id if stamp is not None and stamp.session_id else SCAN_CALLER
        await spawn_integrator_session(first.slug, first.branch, first.sha, caller, project_root)
    except Exception:  # supervision boundary: one failing project must not stop the pass or the daemon
        logger.exception(SCAN_FAILED_LOG, project_root=project_root)

"""The ``claim`` block of ``telec todo show``: who holds an active todo's lifecycle claim."""

from __future__ import annotations

from pathlib import Path

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.driver_start_guard import admission_caller_for
from teleclaude.core.next_machine.driver_admission import (
    AdmissionCaller,
    ClaimHolderReport,
    ClaimStatus,
    claim_holder,
    holder_role,
)
from teleclaude.core.todos_db._show import ClaimBlock


async def claim_block_of(report: ClaimHolderReport, caller: AdmissionCaller) -> ClaimBlock:
    """Shape a holder report as the show payload's block, naming the holder's role when its computer grants it."""
    block = ClaimBlock(status=report.status.value)
    if report.status is ClaimStatus.UNDETERMINED:
        if report.reason:
            block["reason"] = report.reason
        return block
    if report.status is ClaimStatus.FREE:
        return block
    if report.session_id:
        block["session_id"] = report.session_id
    if report.computer:
        block["computer"] = report.computer
    if report.unanswered:
        block["unanswered"] = list(report.unanswered)
    role = await holder_role(report, caller)
    if role:
        block["role"] = role
    return block


async def claim_block_for(project_root: Path, slug: str, identity: CallerIdentity) -> ClaimBlock:
    """Read who holds ``slug`` as the requesting caller and shape it; one caller is carried through every relayed read."""
    caller = admission_caller_for(identity)
    return await claim_block_of(await claim_holder(project_root, slug, caller), caller)

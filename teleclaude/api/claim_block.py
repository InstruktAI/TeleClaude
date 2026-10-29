"""The ``claim`` block of ``telec todo show``: who holds an active todo's lifecycle claim."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, principal_for_carried_caller
from teleclaude.api.driver_start_guard import admission_caller_for
from teleclaude.core.next_machine.driver_admission import (
    CLAIM_READ_DEADLINE_S,
    ClaimHolderReport,
    claim_holder,
    holder_role,
)
from teleclaude.core.todos_db._show import ClaimBlock
from teleclaude.types.todos import ClaimStatus


def claim_block_of(report: ClaimHolderReport, role: str | None) -> ClaimBlock:
    """Shape a holder report as the show payload's block; the role is present only where the caller may read it."""
    block = ClaimBlock(status=report.status)
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
    if role:
        block["role"] = role
    return block


async def claim_block_for(project_root: Path, slug: str, identity: CallerIdentity) -> ClaimBlock:
    """Read who holds ``slug`` as the requesting caller and shape it, the holder's role included, under one deadline.

    The holder read is cleared as a start's relayed requests are. The holder's role is session-record data,
    so it is read under the caller's own reach: through the caller's role resolution on this computer and,
    elsewhere, as the caller's own principal, never the daemon's.
    """
    until = asyncio.get_running_loop().time() + CLAIM_READ_DEADLINE_S
    caller = admission_caller_for(identity)
    report = await claim_holder(project_root, slug, caller, until=until)
    principal = principal_for_carried_caller(identity)
    role = await holder_role(
        report,
        reader=caller_for_role_resolution(identity),
        remote_caller=replace(caller, principal=principal) if principal else None,
        until=until,
    )
    return claim_block_of(report, role)

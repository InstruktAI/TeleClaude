"""Functional bindings for the log-bug-hunter suppression pre-filter.

Drives the real ``LogBugHunterService.maybe_dispatch`` boundary (fixtures in
``conftest.py`` fake only the log fetch and ``create_session``) and asserts the
dispatch decision — never logger calls or internal shape.

Covers @prd#sc-1 (all-suppressed window dispatches nothing), @prd#sc-2 (an
unsuppressed line among suppressed still dispatches), @prd#sc-5 (per-project
isolation), @prd#sc-6 (an elapsed expiry no longer suppresses), and the
defensive case that an uncompilable regex entry never crashes the scan.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teleclaude.constants import ROLE_JOB_RUNNER
from teleclaude.services import log_bug_hunter_suppressions as supp
from teleclaude.services.log_bug_hunter_service import LogBugHunterService
from teleclaude.types.commands import CreateSessionCommand

pytestmark = pytest.mark.functional

ServiceFactory = Callable[[str, str, list[CreateSessionCommand]], LogBugHunterService]

_LOOP_LAG_LINE = "2026-06-25T10:00:00 ERROR HANG_DUMP reason=loop_lag took 1234ms"
_FRESH_ERROR_LINE = "2026-06-25T10:01:00 ERROR database connection refused"


def _suppression(
    *,
    pattern: str,
    match: supp.MatchMode = supp.MatchMode.SUBSTRING,
    expires_at: datetime | None = None,
) -> supp.Suppression:
    return supp.Suppression(
        id="s1",
        pattern=pattern,
        match=match,
        disposition=supp.Disposition.WONTFIX,
        reason="deliberately tolerated",
        expires_at=expires_at,
    )


def _write_ledger(slug: str, *entries: supp.Suppression) -> None:
    supp.save(supp.suppressions_path_for(slug), supp.SuppressionLedger(suppressions=list(entries)))


async def test_fully_suppressed_window_dispatches_nothing(ledger_dir: Path, make_service: ServiceFactory) -> None:
    """@prd#sc-1 — every candidate line suppressed → no session created."""
    _write_ledger("project-a", _suppression(pattern="reason=loop_lag"))
    created: list[CreateSessionCommand] = []
    service = make_service("project-a", _LOOP_LAG_LINE, created)

    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is False
    assert created == []


async def test_unsuppressed_line_among_suppressed_still_dispatches(
    ledger_dir: Path, make_service: ServiceFactory
) -> None:
    """@prd#sc-2 — one fresh signal beside a suppressed one still dispatches."""
    _write_ledger("project-a", _suppression(pattern="reason=loop_lag"))
    created: list[CreateSessionCommand] = []
    window = f"{_LOOP_LAG_LINE}\n{_FRESH_ERROR_LINE}"
    service = make_service("project-a", window, created)

    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is True
    assert len(created) == 1
    # The bug-hunter dispatch is a job-runner filing — the sole no-human
    # lineage root the creation contract permits (UC-WTC26).
    assert created[-1].system_role == ROLE_JOB_RUNNER


async def test_suppression_is_per_project(ledger_dir: Path, make_service: ServiceFactory) -> None:
    """@prd#sc-5 — a suppression for project A leaves project B's scan untouched."""
    _write_ledger("project-a", _suppression(pattern="reason=loop_lag"))
    created: list[CreateSessionCommand] = []
    service = make_service("project-b", _LOOP_LAG_LINE, created)

    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is True
    assert len(created) == 1


async def test_elapsed_expiry_no_longer_suppresses(ledger_dir: Path, make_service: ServiceFactory) -> None:
    """@prd#sc-6 — a suppression past its expiry is inert; its signal dispatches."""
    now = datetime.now(UTC)
    _write_ledger("project-a", _suppression(pattern="reason=loop_lag", expires_at=now - timedelta(hours=1)))
    created: list[CreateSessionCommand] = []
    service = make_service("project-a", _LOOP_LAG_LINE, created)

    dispatched = await service.maybe_dispatch(now=now)

    assert dispatched is True
    assert len(created) == 1


async def test_uncompilable_regex_entry_does_not_crash_scan(ledger_dir: Path, make_service: ServiceFactory) -> None:
    """A regex that fails to compile suppresses nothing and never crashes the scan."""
    _write_ledger("project-a", _suppression(pattern="(unterminated", match=supp.MatchMode.REGEX))
    created: list[CreateSessionCommand] = []
    service = make_service("project-a", _LOOP_LAG_LINE, created)

    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is True
    assert len(created) == 1

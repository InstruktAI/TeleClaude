"""Shared fixtures for the log-bug-hunter suppression tests.

Both the service pre-filter tests and the CLI tests drive the real
``LogBugHunterService.maybe_dispatch`` boundary; ``make_service`` builds one wired
to a faked log fetch and a stubbed ``create_session`` (faking only
process/network), and ``ledger_dir`` isolates each test's suppression ledger.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from teleclaude import paths
from teleclaude.services.log_bug_hunter_service import LogBugHunterService
from teleclaude.types.commands import CreateSessionCommand

ServiceFactory = Callable[[str, str, list[CreateSessionCommand]], LogBugHunterService]


@pytest.fixture
def ledger_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Resolve every suppression ledger under an isolated tmp dir for this test."""
    state_dir = tmp_path / "log-bug-hunter"
    monkeypatch.setattr(paths, "LOG_BUG_HUNTER_STATE_DIR", state_dir)
    return state_dir


@pytest.fixture
def make_service(tmp_path: Path) -> ServiceFactory:
    """Build a real service whose log fetch returns ``output`` and whose dispatch is recorded."""

    def factory(slug: str, output: str, created: list[CreateSessionCommand]) -> LogBugHunterService:
        async def create_session(cmd: CreateSessionCommand) -> dict[str, str]:
            created.append(cmd)
            return {"session_id": "sess-new"}

        async def list_active_sessions() -> list:
            return []

        service = LogBugHunterService(
            create_session=create_session,
            list_active_sessions=list_active_sessions,
            project_root=tmp_path / slug,
            project_slug=slug,
            state_path=tmp_path / f"{slug}.state.json",
        )
        service._run_recent_log_query = lambda: (True, output)
        return service

    return factory

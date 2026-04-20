"""Tests for durable session-scoping ledger storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import teleclaude.session_scoping._store as store_module
from teleclaude.session_scoping._types import WorkspaceScopeLedger


def _make_ledger(
    *,
    workspace_root: str = "/repo",
    workspace_kind: str = "git_worktree",
    strategy: str = "git_worktree",
    agent: str = "codex",
    seen_paths: tuple[str, ...] = ("src/app.py",),
    last_updated: str = "2026-04-11T00:00:00+00:00",
) -> WorkspaceScopeLedger:
    return WorkspaceScopeLedger(
        workspace_root=workspace_root,
        workspace_kind=workspace_kind,
        strategy=strategy,
        agent=agent,
        seen_paths=seen_paths,
        last_updated=last_updated,
    )


def test_store_round_trips_workspace_ledger_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(store_module, "SESSION_SCOPING_DIR", tmp_path)
    ledger = _make_ledger(seen_paths=("src/app.py", "tests/unit/test_app.py"))

    store_module.save_workspace_ledger("session-1", ledger)
    restored = store_module.load_workspace_ledger("session-1", "/repo")

    assert restored == ledger

    ledger_file = next(tmp_path.iterdir())
    payload = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert payload["session_id"] == "session-1"
    assert payload["workspaces"]["/repo"] == {
        "workspace_root": "/repo",
        "workspace_kind": "git_worktree",
        "strategy": "git_worktree",
        "agent": "codex",
        "seen_paths": ["src/app.py", "tests/unit/test_app.py"],
        "last_updated": "2026-04-11T00:00:00+00:00",
    }


def test_store_limits_corruption_to_a_single_session_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(store_module, "SESSION_SCOPING_DIR", tmp_path)
    broken_path = store_module._ledger_path("broken-session")
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{not-json", encoding="utf-8")

    healthy_ledger = _make_ledger(workspace_root="/healthy")
    store_module.save_workspace_ledger("healthy-session", healthy_ledger)

    assert store_module.load_workspace_ledger("broken-session", "/repo") is None
    assert store_module.load_workspace_ledger("healthy-session", "/healthy") == healthy_ledger

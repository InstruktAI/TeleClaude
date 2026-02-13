"""Unit tests for project setup init flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.project_setup import init_flow


def test_init_project_runs_agent_hook_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    """telec init must install global agent hooks before project-local setup."""
    calls: list[str] = []

    monkeypatch.setattr(init_flow, "install_agent_hooks", lambda: calls.append("agent_hooks"))
    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _path: calls.append("ensure_git_repo"))
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _path: calls.append("git_filters"))
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _path: calls.append("gitattributes"))
    monkeypatch.setattr(init_flow, "install_precommit_hook", lambda _path: calls.append("precommit"))
    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _path: calls.append("sync"))
    monkeypatch.setattr(init_flow, "install_docs_watch", lambda _path: calls.append("watch"))
    monkeypatch.setattr(init_flow, "is_macos", lambda: False)

    init_flow.init_project(Path("/tmp/project"))

    assert calls == [
        "agent_hooks",
        "ensure_git_repo",
        "git_filters",
        "gitattributes",
        "precommit",
        "sync",
        "watch",
    ]

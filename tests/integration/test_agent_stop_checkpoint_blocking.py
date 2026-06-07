"""Functional coverage for agent stop checkpoint behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cli.telec.handlers import code
from teleclaude.core.agents import AgentName
from teleclaude.git import Repo
from teleclaude.hooks.checkpoint import get_checkpoint_content
from teleclaude.hooks.checkpoint_flags import has_authored_main_commit_flag

_SPEC = "project/spec/feature/integration/agent-stop-checkpoint-blocking"


def _init_supported_repo(repo_path: Path) -> Repo:
    repo_path.mkdir(parents=True)
    repo = Repo.init(repo_path)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Checkpoint Test")
    repo.git.config("user.email", "checkpoint-test@example.test")
    (repo_path / "teleclaude" / "hooks" / "checkpoint").mkdir(parents=True)
    (repo_path / "teleclaude" / "hooks" / "checkpoint" / "__init__.py").write_text("", encoding="utf-8")
    (repo_path / "agents" / "commands").mkdir(parents=True)
    (repo_path / "agents" / "commands" / "next-work.md").write_text("# Next Work\n", encoding="utf-8")
    (repo_path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    return repo


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_main_branch_review_gate_follows_authored_commit_latch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-author-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)

    first_anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "tracked.txt").write_text("authored\n", encoding="utf-8")
    code._commit_under_lock(
        message="test: authored main commit",
        includes=["tracked.txt"],
        project_root=repo_path,
        system_role=None,
    )

    marker_after_commit = has_authored_main_commit_flag(session_id)
    authored_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=first_anchor_sha,
    )
    marker_after_first_checkpoint = has_authored_main_commit_flag(session_id)
    second_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=first_anchor_sha,
    )

    peer_anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "tracked.txt").write_text("peer\n", encoding="utf-8")
    repo.git.commit("-am", "peer commit")
    peer_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=peer_anchor_sha,
    )

    assert marker_after_commit is True
    assert marker_after_first_checkpoint is False
    assert second_payload is None
    assert peer_payload is None
    assert {"authored_payload": authored_payload} == snapshot

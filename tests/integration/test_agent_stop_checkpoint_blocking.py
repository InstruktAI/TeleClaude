"""Functional coverage for agent stop checkpoint behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.hooks.checkpoint as checkpoint_module
from teleclaude.cli.telec.handlers import code
from teleclaude.constants import CHECKPOINT_MESSAGE
from teleclaude.core.agents import AgentName
from teleclaude.git import Repo
from teleclaude.hooks.checkpoint import get_checkpoint_content, run_heuristics
from teleclaude.hooks.checkpoint._models import CheckpointContext
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_CLEAR_FLAG,
    CHECKPOINT_COMMIT_OBLIGATIONS_FLAG,
    CHECKPOINT_RECHECK_FLAG,
    has_authored_main_commit_flag,
    has_checkpoint_flag,
    read_commit_obligations,
    record_commit_obligations,
    record_integrator_maintenance_marker,
    set_checkpoint_flag,
)
from teleclaude.hooks.receiver import _reset_checkpoint_flags
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

_SPEC = "project/spec/feature/integration/agent-stop-checkpoint-blocking"

# Named constants for instruction identity checks — shared with production code
# (sourced from constants.py FileCategory instruction strings).
_TELEC_SYNC_INSTR = "Run `telec sync`"


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
    (repo_path / "teleclaude" / "core").mkdir(parents=True)
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# initial\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    return repo


def _empty_timeline() -> TurnTimeline:
    return TurnTimeline(tool_calls=[], has_data=True)


def _timeline_with_bash(command: str) -> TurnTimeline:
    record = ToolCallRecord(tool_name="bash", input_data={"command": command})
    return TurnTimeline(tool_calls=[record], has_data=True)


def _timeline_with_bash_commands(commands: list[str]) -> TurnTimeline:
    records = [ToolCallRecord(tool_name="bash", input_data={"command": command}) for command in commands]
    return TurnTimeline(tool_calls=records, has_data=True)


def _checkpoint_payload_for_cycle(
    session_id: str,
    repo_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timeline: TurnTimeline,
) -> str | None:
    _patch_checkpoint_timeline(monkeypatch, timeline)
    return get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )


def _patch_checkpoint_timeline(monkeypatch: pytest.MonkeyPatch, timeline: TurnTimeline) -> None:
    monkeypatch.setattr(checkpoint_module, "extract_effective_tool_calls", lambda *_args, **_kwargs: timeline)


def _disable_commit_quality_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code, "handle_format", lambda _paths: None)
    monkeypatch.setattr(code, "handle_lint", lambda _paths: None)


def _write_parent_and_companion(
    repo_path: Path,
    *,
    slug: str = "checkpoint-ledger-commit-separation",
) -> tuple[str, str]:
    docs_dir = repo_path / "docs" / "project" / "spec" / "feature" / "integration"
    docs_dir.mkdir(parents=True, exist_ok=True)
    parent = docs_dir / "agent-stop-checkpoint-blocking.md"
    companion = docs_dir / f"agent-stop-checkpoint-blocking.{slug}.md"
    parent.write_text("# Parent\n", encoding="utf-8")
    companion.write_text("# Companion\n", encoding="utf-8")
    return parent.relative_to(repo_path).as_posix(), companion.relative_to(repo_path).as_posix()


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
    _disable_commit_quality_gates(monkeypatch)
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'test: authored main commit'"),
    )

    first_anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# authored\n", encoding="utf-8")
    code._commit_under_lock(
        message="test: authored main commit",
        includes=["teleclaude/core/tracked.py"],
        project_root=repo_path,
        system_role=None,
    )

    marker_after_commit = has_authored_main_commit_flag(session_id)
    committed_obligations_after_commit = read_commit_obligations(session_id)
    authored_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=first_anchor_sha,
    )
    marker_after_first_checkpoint = has_authored_main_commit_flag(session_id)
    _reset_checkpoint_flags(session_id)

    peer_anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# peer\n", encoding="utf-8")
    repo.git.commit("-am", "peer commit")
    peer_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=peer_anchor_sha,
    )

    assert marker_after_commit is True
    assert committed_obligations_after_commit == ["daemon code"]
    assert marker_after_first_checkpoint is False
    assert peer_payload is None
    assert {"authored_payload": authored_payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_doc_only_main_commit_does_not_arm_review_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-docs-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    _disable_commit_quality_gates(monkeypatch)

    (repo_path / "docs").mkdir(parents=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    code._commit_under_lock(
        message="docs: add guide",
        includes=["docs/guide.md"],
        project_root=repo_path,
        system_role=None,
    )

    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_directory_pathspec_does_not_arm_review_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit whose actual files are all docs does not arm review, even when
    the requested pathspec contained a directory token like 'docs'."""
    session_id = "checkpoint-dir-pathspec-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    _disable_commit_quality_gates(monkeypatch)

    (repo_path / "docs").mkdir(parents=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "docs: seed guide")
    (repo_path / "docs" / "guide.md").write_text("# Guide\n\nUpdated\n", encoding="utf-8")

    # The user passes the directory 'docs' as a declared include. The gate must
    # resolve the actual committed file list and not treat the directory token as
    # code.
    code._commit_under_lock(
        message="docs: update guide",
        includes=["docs"],
        project_root=repo_path,
        system_role=None,
    )

    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_sealed_commit_records_commit_obligations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-commit-obligations-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    _disable_commit_quality_gates(monkeypatch)

    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# first\n", encoding="utf-8")
    code._commit_under_lock(
        message="test: record committed file",
        includes=["teleclaude/core/tracked.py"],
        project_root=repo_path,
        system_role=None,
    )

    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# second\n", encoding="utf-8")
    (repo_path / "docs").mkdir(parents=True, exist_ok=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    code._commit_under_lock(
        message="test: append committed files",
        includes=["teleclaude/core/tracked.py", "docs/guide.md"],
        project_root=repo_path,
        system_role=None,
    )

    assert read_commit_obligations(session_id) == ["daemon code", "syncable sources"]


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5")
def test_user_prompt_reset_consumes_turn_scoped_checkpoint_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-reset-session"
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    set_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)
    set_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)
    record_commit_obligations(session_id, ["daemon code"])

    _reset_checkpoint_flags(session_id)

    assert has_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG) is False
    assert has_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG) is False
    assert has_checkpoint_flag(session_id, CHECKPOINT_COMMIT_OBLIGATIONS_FLAG) is False
    assert read_commit_obligations(session_id) == []


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_integrator_maintenance_force_fires_on_merge_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "integrator-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    pre_merge_sha = repo.git.rev_parse("HEAD").strip()

    # Simulate a delivery that touched daemon code, deps, setup, and docs
    (repo_path / "teleclaude" / "core" / "service.py").write_text("# service\n", encoding="utf-8")
    (repo_path / "pyproject.toml").write_text("[project]\nname='tc'\n", encoding="utf-8")
    (repo_path / "teleclaude" / "project_setup").mkdir(parents=True, exist_ok=True)
    (repo_path / "teleclaude" / "project_setup" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo_path / "docs").mkdir(parents=True, exist_ok=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "chore: delivery squash")

    post_merge_sha = repo.git.rev_parse("HEAD").strip()
    record_integrator_maintenance_marker(session_id, f"{pre_merge_sha}..{post_merge_sha}")

    # Force-fire path: integrator role, marker present, no turn-local Edit/Write
    anchor_sha = pre_merge_sha
    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=anchor_sha,
        system_role="integrator",
    )

    assert payload is not None
    # No review, commit reminder, or test/log noise (NotIn is not a string-literal violation)
    assert "review gate" not in payload
    assert "telec code commit" not in payload
    assert "Run targeted tests" not in payload
    assert "instrukt-ai-logs" not in payload
    assert {"maintenance_payload": payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_integrator_maintenance_diff_failure_returns_visible_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "integrator-invalid-range-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_integrator_maintenance_marker(session_id, "missing-before..missing-after")

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=None,
        system_role="integrator",
    )

    assert payload == CHECKPOINT_MESSAGE


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_non_integrator_session_no_maintenance_force_fire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "worker-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    anchor_sha = repo.git.rev_parse("HEAD").strip()

    # No marker, non-integrator role, main advanced by someone else
    repo.git.commit("--allow-empty", "-m", "chore: remote advance")

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=anchor_sha,
        system_role="worker",
    )

    # No maintenance force-fire for non-integrator without marker
    assert payload is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_agents_merge_delta_does_not_surface_restart_self_in_maintenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agents/** in a merge delta must NOT surface restart-self in the maintenance
    path — that is a non-main_only action and the integrator's responsibility is
    maintenance (setup/deps/restart/sync), not artifact reload."""
    session_id = "integrator-agents-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    pre_merge_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "agents" / "commands" / "next-deploy.md").write_text("# Deploy\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "feat: add deploy command")
    post_merge_sha = repo.git.rev_parse("HEAD").strip()
    record_integrator_maintenance_marker(session_id, f"{pre_merge_sha}..{post_merge_sha}")

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=pre_merge_sha,
        system_role="integrator",
    )

    # Agents-only merge delta has no main_only categories → no maintenance payload
    # (syncable sources is main_only, so it would surface for docs; agents/** matches
    # syncable sources too, so a payload could surface — but restart-self must not appear)
    if payload is not None:
        assert "restart self" not in payload
        assert "telec sessions restart" not in payload


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_committed_daemon_code_surfaces_maintenance_after_head_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-committed-daemon-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    _disable_commit_quality_gates(monkeypatch)
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'test: daemon commit'"),
    )

    anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# committed daemon\n", encoding="utf-8")
    code._commit_under_lock(
        message="test: daemon commit",
        includes=["teleclaude/core/tracked.py"],
        project_root=repo_path,
        system_role=None,
    )

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=anchor_sha,
    )

    assert read_commit_obligations(session_id) == ["daemon code"]
    assert {"committed_daemon_payload": payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_satisfied_commit_obligation_discharges_and_does_not_refire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-committed-restart-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_commit_obligations(session_id, ["daemon code"])

    restart_payload = _checkpoint_payload_for_cycle(
        session_id,
        repo_path,
        monkeypatch,
        _timeline_with_bash_commands(
            [
                "telec code commit --approved 'test: daemon commit'",
                "make restart",
                "make status",
            ]
        ),
    )
    next_payload = _checkpoint_payload_for_cycle(session_id, repo_path, monkeypatch, _empty_timeline())

    assert read_commit_obligations(session_id) == []
    assert next_payload is None
    assert {"restart_suppressed_payload": restart_payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_surfaced_commit_obligation_discharges_in_later_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-committed-sync-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_commit_obligations(session_id, ["syncable sources"])

    first_payload = _checkpoint_payload_for_cycle(session_id, repo_path, monkeypatch, _empty_timeline())
    satisfied_payload = _checkpoint_payload_for_cycle(
        session_id,
        repo_path,
        monkeypatch,
        _timeline_with_bash("telec sync --skip-deploy"),
    )
    next_payload = _checkpoint_payload_for_cycle(session_id, repo_path, monkeypatch, _empty_timeline())

    assert read_commit_obligations(session_id) == []
    assert next_payload is None
    assert {"first_payload": first_payload, "satisfied_payload": satisfied_payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_committed_code_persists_only_main_only_maintenance_obligations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-main-only-obligations-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    _disable_commit_quality_gates(monkeypatch)

    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# committed daemon\n", encoding="utf-8")
    (repo_path / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    (repo_path / "tests" / "integration" / "test_example.py").write_text(
        "def test_example():\n    pass\n", encoding="utf-8"
    )
    code._commit_under_lock(
        message="test: record maintenance subset",
        includes=["teleclaude/core/tracked.py", "tests/integration/test_example.py"],
        project_root=repo_path,
        system_role=None,
    )

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert read_commit_obligations(session_id) == ["daemon code"]
    assert payload is not None
    assert {"main_only_payload": payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_commit_obligations_read_failure_returns_visible_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-committed-read-failure-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)

    def raise_marker_error(_session_id: str) -> list[str]:
        raise OSError("marker unavailable")

    monkeypatch.setattr(checkpoint_module, "read_commit_obligations", raise_marker_error)

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert payload == CHECKPOINT_MESSAGE


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_docs_dir_change_surfaces_telec_sync(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["docs/spec.md"], _empty_timeline(), context)

    assert _TELEC_SYNC_INSTR in result.required_actions
    assert {"docs_sync_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_docs_dir_telec_sync_suppressed_with_evidence(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))
    timeline = _timeline_with_bash(_TELEC_SYNC_INSTR)

    result = run_heuristics(["docs/spec.md"], timeline, context)

    assert _TELEC_SYNC_INSTR not in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_worktree_omits_main_only_categories_from_summary_and_actions(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    repo.git.checkout("-b", "feature/x")  # off main — a worktree branch
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["agents/commands/next-work.md", "docs/spec.md"], _empty_timeline(), context)

    # syncable sources (main_only) is deferred to integration off main; the summary and
    # actions hold only the non-main_only agent-artifacts category.
    assert _TELEC_SYNC_INSTR not in result.required_actions
    assert {"worktree_categories": result.categories, "worktree_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_code_change_with_outstanding_actions_shown_in_summary(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # hook runtime has no per-category action; while its log/test actions are outstanding
    # it drives them, so it appears in the summary alongside those actions.
    result = run_heuristics(["teleclaude/hooks/checkpoint/_evidence.py"], _empty_timeline(), context)

    assert {"hook_categories": result.categories, "hook_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_code_change_without_outstanding_actions_omitted_from_summary(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))
    timeline = _timeline_with_bash_commands(["uv run pytest tests/foo.py", "instrukt-ai-logs teleclaude --since 5m"])

    # hook runtime auto-applies; once its log/test actions are satisfied it has nothing
    # outstanding, so it is omitted from both the summary and the required actions.
    result = run_heuristics(["teleclaude/hooks/checkpoint/_evidence.py"], timeline, context)

    assert not result.categories
    assert not result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP13")
def test_parent_snippet_edit_with_pending_companion_surfaces_mirror_action(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    parent_rel, _companion_rel = _write_parent_and_companion(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics([parent_rel], _empty_timeline(), context)

    assert {"parent_only_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP13")
def test_parent_and_companion_change_suppresses_mirror_action(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    parent_rel, companion_rel = _write_parent_and_companion(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics([parent_rel, companion_rel], _empty_timeline(), context)

    assert {"parent_and_companion_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP13")
def test_parent_snippet_without_companion_suppresses_mirror_action(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    docs_dir = repo_path / "docs" / "project" / "spec" / "feature" / "integration"
    docs_dir.mkdir(parents=True, exist_ok=True)
    parent = docs_dir / "agent-stop-checkpoint-blocking.md"
    parent.write_text("# Parent\n", encoding="utf-8")
    parent_rel = parent.relative_to(repo_path).as_posix()
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics([parent_rel], _empty_timeline(), context)

    assert {"parent_without_companion_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP13")
def test_companion_only_change_suppresses_mirror_action(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    _parent_rel, companion_rel = _write_parent_and_companion(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics([companion_rel], _empty_timeline(), context)

    assert {"companion_only_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_agent_command_change_surfaces_both_restart_and_telec_sync(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["agents/commands/next-build.md"], _empty_timeline(), context)

    assert _TELEC_SYNC_INSTR in result.required_actions
    assert {"agent_cmd_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP9")
def test_bare_md_outside_docs_stays_no_action(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["README.md"], _empty_timeline(), context)

    # Bare .md is no-action only: no category instructions
    assert result.required_actions == []
    assert result.categories == []


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP4")
def test_make_install_surfaces_for_makefile_change(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["Makefile"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"makefile_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP4")
def test_make_install_surfaces_for_install_dir_change(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["teleclaude/install/script.sh"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"install_dir_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP4")
def test_pyproject_toml_routes_to_uv_sync_not_make_install(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["pyproject.toml"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"pyproject_result": result.required_actions} == snapshot

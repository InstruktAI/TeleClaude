"""Functional coverage for agent stop checkpoint behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import teleclaude.hooks.checkpoint as checkpoint_module
import teleclaude.session_scoping._extractors.claude as claude_extractor
import teleclaude.session_scoping._extractors.codex as codex_extractor
from teleclaude.checkpoint_model import base_checkpoint_model
from teleclaude.cli.telec.handlers import code
from teleclaude.constants import CHECKPOINT_MESSAGE
from teleclaude.core.agents import AgentName
from teleclaude.git import Repo
from teleclaude.hooks.checkpoint import (
    _is_checkpoint_project_supported,
    _post_commit_review_instruction,
    get_checkpoint_content,
    run_heuristics,
)
from teleclaude.hooks.checkpoint._models import CheckpointContext
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_CLEAR_FLAG,
    CHECKPOINT_COMMIT_OBLIGATIONS_FLAG,
    CHECKPOINT_RECHECK_FLAG,
    has_authored_main_commit_flag,
    has_checkpoint_flag,
    read_commit_obligations,
    record_authored_main_commit,
    record_commit_obligations,
    record_integrator_maintenance_marker,
    set_checkpoint_flag,
)
from teleclaude.hooks.receiver import _reset_checkpoint_flags
from teleclaude.session_scoping import ScopedPathsResult
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

_SPEC = "project/spec/feature/integration/agent-stop-checkpoint-blocking"

# Named constants for instruction identity checks — the surfaced `run` strings of
# the base/overlay checkpoint actions.
_TELEC_SYNC_INSTR = "Run `telec sync`"
_MAKE_RESTART_INSTR = "Run `make restart`"
_SIDE_RESTART_INSTR = "Run `./restart.sh`"

# TeleClaude's own checkpoint overlay, mirrored from teleclaude.yml so the fixture
# repo dogfoods the same base ⊕ overlay model the platform hands every project
# (SC-3 parity is verified against this overlay).
_TELECLAUDE_CHECKPOINT_OVERLAY = {
    "actions": {
        "restart": {"run": "Run `make restart`", "evidence": ["make restart"], "main_only": True, "precedence": 30},
        "deps": {
            "run": "Install updated dependencies: `uv sync`",
            "evidence": ["uv sync", "make install"],
            "main_only": True,
            "precedence": 20,
        },
        "tui-reload": {
            "run": "Run `pkill -SIGUSR2 -f -- '\\.venv/bin/telec$|teleclaude\\.cli\\.telec($| )'`",
            "evidence": ["pkill -SIGUSR2", "kill -USR2"],
            "evidence_must_follow_last_mutation": True,
            "precedence": 40,
        },
    },
    "code": {"scope": {"include": ["teleclaude/**/*.py", "tests/**/*.py"]}},
    "bindings": [
        {
            "scope": {
                "include": ["teleclaude/**/*.py"],
                "exclude": [
                    "teleclaude/hooks/**",
                    "teleclaude/cli/**",
                    "teleclaude/utils/**",
                    "teleclaude/quality/**",
                    "teleclaude/session_scoping/**",
                    "teleclaude/project_setup/**",
                    "teleclaude/codegen/**",
                    "teleclaude/resource_validation/**",
                    "teleclaude/entrypoints/**",
                    "teleclaude/tagging/**",
                    "teleclaude/helpers/**",
                ],
                "override": [
                    "teleclaude/cli/__init__.py",
                    "teleclaude/cli/telec/__init__.py",
                    "teleclaude/cli/telec/surface.py",
                    "teleclaude/cli/telec/surface_types.py",
                    "teleclaude/cli/telec/auth.py",
                    "teleclaude/cli/telec/help.py",
                    "teleclaude/cli/telec/_shared.py",
                    "teleclaude/cli/telec/_run_tui.py",
                    "teleclaude/cli/tool_client.py",
                    "teleclaude/cli/session_auth.py",
                ],
            },
            "actions": ["restart"],
        },
        {"scope": {"include": ["config.yml"]}, "actions": ["restart"]},
        {"scope": {"include": ["pyproject.toml", "requirements*.txt"]}, "actions": ["deps"]},
        {
            "scope": {"include": ["teleclaude/install/**", "teleclaude/project_setup/**", "templates/**"]},
            "actions": ["install"],
        },
        {"scope": {"include": ["teleclaude/cli/tui/**"]}, "actions": ["tui-reload"]},
    ],
}


def _write_teleclaude_overlay(repo_path: Path) -> None:
    """Write the onboarded-project marker + TeleClaude checkpoint overlay."""
    config = {
        "project_name": "TeleClaude",
        "project_slug": "teleclaude",
        "checkpoint": _TELECLAUDE_CHECKPOINT_OVERLAY,
    }
    with open(repo_path / "teleclaude.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f)


@pytest.fixture(autouse=True)
def _fake_current_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep checkpoint branch decisions at the process seam."""
    monkeypatch.setattr(checkpoint_module, "_current_branch", lambda _project_path: "main")


def _init_supported_project(repo_path: Path) -> None:
    repo_path.mkdir(parents=True)
    _write_teleclaude_overlay(repo_path)
    (repo_path / "teleclaude" / "hooks" / "checkpoint").mkdir(parents=True)
    (repo_path / "teleclaude" / "hooks" / "checkpoint" / "__init__.py").write_text("", encoding="utf-8")
    (repo_path / "agents" / "commands").mkdir(parents=True)
    (repo_path / "agents" / "commands" / "next-work.md").write_text("# Next Work\n", encoding="utf-8")
    (repo_path / "teleclaude" / "core").mkdir(parents=True)
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# initial\n", encoding="utf-8")


def _init_supported_git_project(repo_path: Path) -> Repo:
    _init_supported_project(repo_path)
    repo = Repo.init(repo_path)
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test User")
    repo.git.branch("-M", "main")
    repo.git.add(A=True)
    repo.index.commit("test: baseline")
    return repo


def _scoped_paths(paths: tuple[str, ...] = ()) -> ScopedPathsResult:
    return ScopedPathsResult(
        paths=paths,
        scope_mode="turn_delta",
        workspace_kind="non_git",
        strategy="test",
        ledger_updated=False,
    )


def _patch_scoped_paths(monkeypatch: pytest.MonkeyPatch, paths: tuple[str, ...] = ()) -> None:
    monkeypatch.setattr(checkpoint_module, "resolve_scoped_paths", lambda **_kwargs: _scoped_paths(paths))


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
    paths: tuple[str, ...] = (),
) -> str | None:
    _patch_checkpoint_timeline(monkeypatch, timeline)
    _patch_scoped_paths(monkeypatch, paths)
    return get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )


def _patch_checkpoint_timeline(monkeypatch: pytest.MonkeyPatch, timeline: TurnTimeline) -> None:
    monkeypatch.setattr(checkpoint_module, "extract_effective_tool_calls", lambda *_args, **_kwargs: timeline)


def _patch_claude_timeline(monkeypatch: pytest.MonkeyPatch, timeline: TurnTimeline) -> None:
    monkeypatch.setattr(claude_extractor, "extract_effective_tool_calls", lambda *_args, **_kwargs: timeline)


def _patch_codex_timeline(monkeypatch: pytest.MonkeyPatch, timeline: TurnTimeline) -> None:
    monkeypatch.setattr(codex_extractor, "extract_effective_tool_calls", lambda *_args, **_kwargs: timeline)


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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'test: authored main commit'"),
    )
    scoped_paths = iter([("teleclaude/core/tracked.py",), ()])
    monkeypatch.setattr(checkpoint_module, "resolve_scoped_paths", lambda **_kwargs: _scoped_paths(next(scoped_paths)))

    record_authored_main_commit(session_id)
    record_commit_obligations(session_id, ["restart"])

    marker_after_commit = has_authored_main_commit_flag(session_id)
    committed_obligations_after_commit = read_commit_obligations(session_id)
    authored_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha="first-anchor",
    )
    marker_after_first_checkpoint = has_authored_main_commit_flag(session_id)
    _reset_checkpoint_flags(session_id)

    peer_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha="peer-anchor",
    )

    assert marker_after_commit is True
    assert committed_obligations_after_commit == ["restart"]
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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    monkeypatch.setattr(code, "_current_branch", lambda _project_root: "main")

    code._record_commit_checkpoint_markers(repo_path, ["docs/guide.md"])

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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    monkeypatch.setattr(code, "_current_branch", lambda _project_root: "main")

    # The commit gate has resolved the requested directory pathspec (`docs`) to
    # the actual committed doc file. The marker seam must classify that file
    # list, not the original directory token.
    code._record_commit_checkpoint_markers(repo_path, ["docs/guide.md"])

    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_sealed_commit_records_commit_obligations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-commit-obligations-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    monkeypatch.setattr(code, "_current_branch", lambda _project_root: "main")

    code._record_commit_checkpoint_markers(repo_path, ["teleclaude/core/tracked.py", "docs/guide.md"])

    assert read_commit_obligations(session_id) == ["restart", "sync"]
    assert has_authored_main_commit_flag(session_id) is True


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
    record_commit_obligations(session_id, ["restart"])

    _reset_checkpoint_flags(session_id)

    assert has_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG) is False
    assert has_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG) is False
    assert has_checkpoint_flag(session_id, CHECKPOINT_COMMIT_OBLIGATIONS_FLAG) is False
    assert read_commit_obligations(session_id) == []


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP1")
def test_claude_shell_mutation_path_surfaces_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-claude-shell-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    timeline = _timeline_with_bash("python - <<'PY' > teleclaude/core/tracked.py\nprint('# shell mutation')\nPY")
    _patch_checkpoint_timeline(monkeypatch, timeline)
    _patch_claude_timeline(monkeypatch, timeline)
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py",))

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=str(tmp_path / "transcript.jsonl"),
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert payload is not None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP1")
def test_claude_compact_redirection_path_surfaces_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-claude-compact-redirection-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    timeline = _timeline_with_bash("printf '# shell mutation\\n' >teleclaude/core/tracked.py")
    _patch_checkpoint_timeline(monkeypatch, timeline)
    _patch_claude_timeline(monkeypatch, timeline)
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py",))

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=str(tmp_path / "transcript.jsonl"),
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert payload is not None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP1")
def test_codex_shell_mutation_path_surfaces_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-codex-shell-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    timeline = _timeline_with_bash("printf '# shell mutation\\n' >teleclaude/core/tracked.py")
    _patch_checkpoint_timeline(monkeypatch, timeline)
    _patch_codex_timeline(monkeypatch, timeline)
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py",))

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=str(tmp_path / "transcript.jsonl"),
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert payload is not None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP16")
def test_claude_descriptor_redirect_does_not_surface_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-claude-descriptor-redirect-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    timeline = _timeline_with_bash("grep -n 'foo' teleclaude/core/tracked.py 2>/dev/null")
    _patch_checkpoint_timeline(monkeypatch, timeline)
    _patch_claude_timeline(monkeypatch, timeline)
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py",))

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=str(tmp_path / "transcript.jsonl"),
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert payload is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP16")
def test_claude_numbered_descriptor_file_redirect_surfaces_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-claude-descriptor-file-redirect-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    timeline = _timeline_with_bash("printf '# shell mutation\\n' 2>teleclaude/core/tracked.py")
    _patch_checkpoint_timeline(monkeypatch, timeline)
    _patch_claude_timeline(monkeypatch, timeline)
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py",))

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=str(tmp_path / "transcript.jsonl"),
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert payload is not None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_integrator_maintenance_force_fires_on_merge_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "integrator-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(
        checkpoint_module,
        "_git_diff_names",
        lambda _project_path, _range_expr: [
            "teleclaude/core/service.py",
            "pyproject.toml",
            "teleclaude/project_setup/setup.sh",
            "docs/guide.md",
        ],
    )

    pre_merge_sha = "pre-merge"
    post_merge_sha = "post-merge"
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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_integrator_maintenance_marker(session_id, "missing-before..missing-after")
    monkeypatch.setattr(
        checkpoint_module,
        "_git_diff_names",
        lambda _project_path, _range_expr: (_ for _ in ()).throw(RuntimeError("bad range")),
    )

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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    _patch_scoped_paths(monkeypatch)

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha="anchor",
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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(
        checkpoint_module,
        "_git_diff_names",
        lambda _project_path, _range_expr: ["agents/commands/next-deploy.md"],
    )

    pre_merge_sha = "pre-merge"
    post_merge_sha = "post-merge"
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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'test: daemon commit'"),
    )
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py",))

    record_authored_main_commit(session_id)
    record_commit_obligations(session_id, ["restart"])

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha="anchor",
    )

    assert read_commit_obligations(session_id) == ["restart"]
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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_commit_obligations(session_id, ["restart"])

    restart_payload = _checkpoint_payload_for_cycle(
        session_id,
        repo_path,
        monkeypatch,
        _timeline_with_bash_commands(
            [
                "telec code commit --approved 'test: daemon commit'",
                "make restart 2>&1 | tail -15",
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
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_commit_obligations(session_id, ["sync"])

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


def _patch_all_timelines(monkeypatch: pytest.MonkeyPatch, timeline: TurnTimeline) -> None:
    """Surface one timeline to both the checkpoint heuristics and the path extractor.

    `resolve_scoped_paths` derives turn-local files from the agent-native
    extractor (`codex.extract_effective_tool_calls`), a binding distinct from the
    checkpoint module's own. Patching both makes the structured mutators in
    `timeline` land in `effective_files`, reproducing a turn whose only changes
    are committed docs/** snippets.
    """
    monkeypatch.setattr(codex_extractor, "extract_effective_tool_calls", lambda *_a, **_k: timeline)
    _patch_checkpoint_timeline(monkeypatch, timeline)


def _docs_turn_timeline(repo_path: Path, *, synced: bool) -> TurnTimeline:
    records = [
        ToolCallRecord(tool_name="write", input_data={"file_path": str(repo_path / "docs" / "notes.md")}),
        ToolCallRecord(tool_name="bash", input_data={"command": "telec code commit --approved 'docs: add notes'"}),
    ]
    if synced:
        records.append(ToolCallRecord(tool_name="bash", input_data={"command": "telec sync"}))
    return TurnTimeline(tool_calls=records, has_data=True)


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP15")
def test_committed_and_synced_doc_only_turn_fires_no_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-docs-satisfied-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    _patch_all_timelines(monkeypatch, _docs_turn_timeline(repo_path, synced=True))
    _patch_scoped_paths(monkeypatch, ("docs/notes.md",))
    satisfied_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    _patch_all_timelines(monkeypatch, _docs_turn_timeline(repo_path, synced=False))
    _patch_scoped_paths(monkeypatch, ("docs/notes.md",))
    unsynced_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert satisfied_payload is None
    assert unsynced_payload is not None
    assert {"unsynced_doc_payload": unsynced_payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_committed_code_persists_only_main_only_maintenance_obligations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-main-only-obligations-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'test: record maintenance subset'"),
    )
    _patch_scoped_paths(monkeypatch, ("teleclaude/core/tracked.py", "tests/integration/test_example.py"))
    record_authored_main_commit(session_id)
    record_commit_obligations(session_id, ["restart"])

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert read_commit_obligations(session_id) == ["restart"]
    assert payload is not None
    assert {"main_only_payload": payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP17")
def test_worktree_sealed_commit_records_no_main_only_maintenance_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-worktree-commit-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_git_project(repo_path)
    worktree_path = repo_path / "trees" / "checkpoint-restart"
    repo.git.worktree("add", "-b", "checkpoint-restart", str(worktree_path), "main")
    (worktree_path / "teleclaude" / "core" / "tracked.py").unlink()

    monkeypatch.chdir(worktree_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree_path))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'fix(checkpoint): delete worktree daemon file'"),
    )
    _patch_scoped_paths(monkeypatch)

    code.handle_code_commit(["--approved", "fix(checkpoint): delete worktree daemon file"])
    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=None,
    )

    assert read_commit_obligations(session_id) == []
    assert payload is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP12")
def test_commit_obligations_read_failure_returns_visible_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-committed-read-failure-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    _patch_scoped_paths(monkeypatch)

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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))
    timeline = _timeline_with_bash(_TELEC_SYNC_INSTR)

    result = run_heuristics(["docs/spec.md"], timeline, context)

    assert _TELEC_SYNC_INSTR not in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_post_commit_review_discharged_by_review_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checkpoint_module, "_current_branch", lambda _project_path: "main")
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(tmp_path))
    model = base_checkpoint_model("teleclaude")
    review_instr = _post_commit_review_instruction()

    # No dispatch evidence: the review obligation surfaces after an authored commit.
    bare = run_heuristics(
        [],
        _empty_timeline(),
        context,
        authored_main_commit=True,
        model=model,
    )
    assert review_instr in bare.required_actions
    assert bare.post_commit_review_action_required is True

    # A fresh /next-review-commits run discharges it.
    fresh = run_heuristics(
        [],
        _timeline_with_bash("telec sessions run --command /next-review-commits --args abc123 --agent codex --mode med"),
        context,
        authored_main_commit=True,
        model=model,
    )
    assert review_instr not in fresh.required_actions
    assert fresh.post_commit_review_action_required is False

    # A remediation sent to an already-open reviewer discharges it too.
    remediation = run_heuristics(
        [],
        _timeline_with_bash('telec sessions send sess-9 "review commits abc123 — remediation of findings"'),
        context,
        authored_main_commit=True,
        model=model,
    )
    assert review_instr not in remediation.required_actions

    # An incidental mention that is not a sessions command does not discharge it.
    incidental = run_heuristics(
        [],
        _timeline_with_bash("echo run /next-review-commits later"),
        context,
        authored_main_commit=True,
        model=model,
    )
    assert review_instr in incidental.required_actions

    # A sessions message that merely *mentions* the command (e.g. a question) is
    # not a dispatch and must not discharge the gate.
    mention = run_heuristics(
        [],
        _timeline_with_bash('telec sessions send sess-1 "should I run /next-review-commits?"'),
        context,
        authored_main_commit=True,
        model=model,
    )
    assert review_instr in mention.required_actions

    # A `sessions run` of a different command is not a review dispatch.
    other_run = run_heuristics(
        [],
        _timeline_with_bash("telec sessions run --command /next-build --args abc123 --agent codex"),
        context,
        authored_main_commit=True,
        model=model,
    )
    assert review_instr in other_run.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_post_commit_review_defers_while_commit_action_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checkpoint_module, "_current_branch", lambda _project_path: "main")
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(tmp_path))
    review_instr = _post_commit_review_instruction()

    result = run_heuristics(
        ["teleclaude/hooks/checkpoint/__init__.py"],
        _empty_timeline(),
        context,
        authored_main_commit=True,
        model=base_checkpoint_model("teleclaude"),
    )

    assert result.commit_action_required is True
    assert result.post_commit_review_action_required is False
    assert review_instr not in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_review_dispatched_zero_enforcement_force_fire_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-review-dispatched-silent-session"
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(checkpoint_module, "_is_checkpoint_project_supported", lambda _project_path: True)
    monkeypatch.setattr(checkpoint_module, "_current_branch", lambda _project_path: "main")
    monkeypatch.setattr(
        checkpoint_module, "load_checkpoint_model", lambda _project_path: base_checkpoint_model("teleclaude")
    )
    monkeypatch.setattr(
        checkpoint_module,
        "resolve_scoped_paths",
        lambda **_kwargs: ScopedPathsResult(
            paths=(),
            scope_mode="turn_delta",
            workspace_kind="non_git",
            strategy="test",
            ledger_updated=False,
        ),
    )
    record_authored_main_commit(session_id)

    payload = _checkpoint_payload_for_cycle(
        session_id,
        tmp_path,
        monkeypatch,
        _timeline_with_bash("telec sessions run --command /next-review-commits --args abc123 --agent codex"),
    )

    assert payload is None
    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_authored_main_marker_survives_dirty_turn_and_surfaces_on_clean_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-review-defer-clean-session"
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(checkpoint_module, "_is_checkpoint_project_supported", lambda _project_path: True)
    monkeypatch.setattr(checkpoint_module, "_current_branch", lambda _project_path: "main")
    monkeypatch.setattr(
        checkpoint_module, "load_checkpoint_model", lambda _project_path: base_checkpoint_model("teleclaude")
    )
    monkeypatch.setattr(checkpoint_module, "_scope_git_files_to_current_turn", lambda files, *_args: files)
    scoped_paths = iter(
        [
            ("teleclaude/core/tracked.py",),
            (),
        ]
    )
    monkeypatch.setattr(
        checkpoint_module,
        "resolve_scoped_paths",
        lambda **_kwargs: ScopedPathsResult(
            paths=next(scoped_paths),
            scope_mode="turn_delta",
            workspace_kind="non_git",
            strategy="test",
            ledger_updated=False,
        ),
    )
    record_authored_main_commit(session_id)

    _patch_checkpoint_timeline(monkeypatch, _timeline_with_bash("printf '# dirty\\n' >teleclaude/core/tracked.py"))
    dirty_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(tmp_path),
        turn_anchor_sha=None,
    )
    marker_after_dirty_turn = has_authored_main_commit_flag(session_id)

    _patch_checkpoint_timeline(monkeypatch, _empty_timeline())
    clean_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(tmp_path),
        turn_anchor_sha=None,
    )

    assert dirty_payload is not None
    assert marker_after_dirty_turn is True
    assert clean_payload is not None
    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_worktree_omits_main_only_categories_from_summary_and_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    monkeypatch.setattr(checkpoint_module, "_current_branch", lambda _project_path: "feature/x")
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
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # hook runtime has no per-category action; while its log/test actions are outstanding
    # it drives them, so it appears in the summary alongside those actions.
    result = run_heuristics(["teleclaude/hooks/checkpoint/_evidence.py"], _empty_timeline(), context)

    assert {"hook_categories": result.categories, "hook_actions": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_code_change_all_evidence_still_appears_in_changed_summary(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))
    timeline = _timeline_with_bash_commands(["uv run pytest tests/foo.py", "instrukt-ai-logs teleclaude --since 5m"])

    # A hooks .py file is in the `code` scope (test + log-check). Once both actions
    # are satisfied no action is surfaced — but the action ids still appear in the
    # Changed summary because it is the raw owed-action set, independent of suppression.
    result = run_heuristics(["teleclaude/hooks/checkpoint/_evidence.py"], timeline, context)

    assert result.categories == ["log-check", "test"]
    assert not result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP13")
def test_parent_snippet_edit_with_pending_companion_surfaces_mirror_action(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
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
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["pyproject.toml"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"pyproject_result": result.required_actions} == snapshot


# ---------------------------------------------------------------------------
# UC-CP14 — glob fix + daemon-imported CLI reclassification
# ---------------------------------------------------------------------------


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP14")
def test_toplevel_daemon_file_categorized_as_daemon_code(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # teleclaude/constants.py sits at exactly one directory depth — the old fnmatch-based
    # matcher required at least one sub-directory inside teleclaude/ (due to the explicit
    # "/" after "**"), so this file was silently uncategorized.
    result = run_heuristics(["teleclaude/constants.py"], _empty_timeline(), context)

    assert result.categories == ["restart", "log-check", "test"]
    assert _MAKE_RESTART_INSTR in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP14")
def test_daemon_imported_cli_module_categorized_as_daemon_code(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # teleclaude/cli/telec/surface.py is imported by the daemon at startup and must
    # trigger a restart. It lives under the general teleclaude/cli/** exclusion but is
    # explicitly whitelisted in override_patterns.
    result = run_heuristics(["teleclaude/cli/telec/surface.py"], _empty_timeline(), context)

    assert result.categories == ["restart", "log-check", "test"]
    assert _MAKE_RESTART_INSTR in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP14")
def test_pure_subprocess_cli_module_not_daemon_code(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # teleclaude/cli/telec/handlers/code.py is invoked as a subprocess, not imported by
    # the daemon — it is excluded from the restart binding and does not require make
    # restart. It is still in the `code` scope, so it owes test + log-check.
    result = run_heuristics(["teleclaude/cli/telec/handlers/code.py"], _empty_timeline(), context)

    assert "restart" not in result.categories
    assert result.categories == ["log-check", "test"]
    assert _MAKE_RESTART_INSTR not in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP14")
def test_transitively_loaded_cli_module_categorized_as_daemon_code(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # teleclaude/cli/telec/auth.py is loaded transitively when tool_access.py imports
    # teleclaude.cli.telec (__init__.py imports auth). Previously omitted from
    # override_patterns; editing it would have been silently uncategorized.
    result = run_heuristics(["teleclaude/cli/telec/auth.py"], _empty_timeline(), context)

    assert result.categories == ["restart", "log-check", "test"]
    assert _MAKE_RESTART_INSTR in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP14")
def test_cli_package_init_categorized_as_daemon_code(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    # teleclaude/cli/__init__.py is loaded as the parent package when the daemon
    # imports teleclaude.cli.telec; editing it changes the daemon's loaded module set.
    result = run_heuristics(["teleclaude/cli/__init__.py"], _empty_timeline(), context)

    assert result.categories == ["restart", "log-check", "test"]
    assert _MAKE_RESTART_INSTR in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP14")
def test_committed_toplevel_daemon_code_surfaces_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-toplevel-daemon-commit-session"
    repo_path = tmp_path / "repo"
    _init_supported_project(repo_path)

    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    _patch_checkpoint_timeline(
        monkeypatch,
        _timeline_with_bash("telec code commit --approved 'test: update toplevel daemon file'"),
    )
    _patch_scoped_paths(monkeypatch, ("teleclaude/constants.py",))

    record_authored_main_commit(session_id)
    record_commit_obligations(session_id, ["restart"])

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha="anchor",
    )

    assert read_commit_obligations(session_id) == ["restart"]
    assert {"toplevel_daemon_payload": payload} == snapshot


# ---------------------------------------------------------------------------
# UC-CP16 — project-agnostic base ⊕ overlay (SC-1, SC-2, SC-5) + onboarded gate
# ---------------------------------------------------------------------------


def _init_side_project(repo_path: Path, *, checkpoint: object = None, raw_yaml: str | None = None) -> None:
    """A non-TeleClaude onboarded repo: a teleclaude.yml, no TeleClaude package tree."""
    repo_path.mkdir(parents=True)
    if raw_yaml is not None:
        (repo_path / "teleclaude.yml").write_text(raw_yaml, encoding="utf-8")
    else:
        body: dict[str, object] = {  # guard: loose-dict - test config YAML serialization boundary
            "project_name": "Side",
            "project_slug": "side",
        }
        if checkpoint is not None:
            body["checkpoint"] = checkpoint
        with open(repo_path / "teleclaude.yml", "w", encoding="utf-8") as f:
            yaml.safe_dump(body, f)
    (repo_path / "README.md").write_text("# Side\n", encoding="utf-8")


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP16")
def test_onboarded_project_without_teleclaude_package_is_supported(tmp_path: Path) -> None:
    """The checkpoint gate keys on teleclaude.yml, not TeleClaude package markers."""
    onboarded = tmp_path / "side"
    _init_side_project(onboarded)
    bare = tmp_path / "bare"
    bare.mkdir()

    assert _is_checkpoint_project_supported(str(onboarded)) is True
    assert _is_checkpoint_project_supported(str(bare)) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP16")
def test_base_actions_fire_for_any_onboarded_project(tmp_path: Path) -> None:
    """SC-2: the platform-universal base fires regardless of language or overlay."""
    repo_path = tmp_path / "side"
    _init_side_project(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["docs/guide.md"], _empty_timeline(), context)

    assert _TELEC_SYNC_INSTR in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP16")
def test_declared_overlay_action_surfaces_alongside_base(tmp_path: Path) -> None:
    """SC-1: a project's declared overlay action is nudged alongside the base."""
    overlay = {
        "actions": {"restart-app": {"run": _SIDE_RESTART_INSTR, "evidence": ["./restart.sh"], "precedence": 30}},
        "bindings": [{"scope": {"include": ["src/**/*.js"]}, "actions": ["restart-app"]}],
    }
    repo_path = tmp_path / "side"
    _init_side_project(repo_path, checkpoint=overlay)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["src/app.js", "docs/guide.md"], _empty_timeline(), context)

    assert _SIDE_RESTART_INSTR in result.required_actions
    assert _TELEC_SYNC_INSTR in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP16")
def test_unreadable_overlay_degrades_to_base_only(tmp_path: Path) -> None:
    """SC-5: a malformed overlay fails open to base-only without erroring."""
    # A checkpoint action missing its required `run` makes the overlay invalid.
    raw = "project_slug: side\ncheckpoint:\n  actions:\n    broken:\n      evidence: [x]\n"
    repo_path = tmp_path / "side"
    _init_side_project(repo_path, raw_yaml=raw)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["docs/guide.md"], _empty_timeline(), context)

    assert _TELEC_SYNC_INSTR in result.required_actions

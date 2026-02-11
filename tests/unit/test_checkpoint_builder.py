"""Tests for the checkpoint heuristic engine and message builder."""

from types import SimpleNamespace

from teleclaude.core.agents import AgentName
from teleclaude.hooks.checkpoint import (
    CheckpointContext,
    _categorize_files,
    _check_edit_hygiene,
    _check_error_state,
    _check_slug_alignment,
    _command_likely_mutates_files,
    _enrich_error,
    _extract_turn_file_signals,
    _get_uncommitted_files,
    _has_evidence,
    _is_docs_only,
    _scope_git_files_to_current_turn,
    build_checkpoint_message,
    get_checkpoint_content,
    run_heuristics,
)
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline


def _empty_timeline() -> TurnTimeline:
    return TurnTimeline(tool_calls=[], has_data=False)


def _timeline_with(*records: ToolCallRecord) -> TurnTimeline:
    return TurnTimeline(tool_calls=list(records), has_data=True)


def _bash_record(command: str, had_error: bool = False, result_snippet: str = "") -> ToolCallRecord:
    return ToolCallRecord(
        tool_name="Bash",
        input_data={"command": command},
        had_error=had_error,
        result_snippet=result_snippet,
    )


def _edit_record(file_path: str) -> ToolCallRecord:
    return ToolCallRecord(tool_name="Edit", input_data={"file_path": file_path})


def _read_record(file_path: str) -> ToolCallRecord:
    return ToolCallRecord(tool_name="Read", input_data={"file_path": file_path})


def _default_context(project_path: str = "", working_slug: str | None = None) -> CheckpointContext:
    return CheckpointContext(
        project_path=project_path,
        working_slug=working_slug,
        agent_name=AgentName.CLAUDE,
    )


# ---------------------------------------------------------------------------
# File categorization (R2)
# ---------------------------------------------------------------------------


def test_daemon_code_maps_to_restart():
    cats = _categorize_files(["teleclaude/core/foo.py"])
    names = [c.name for c in cats]
    assert "daemon code" in names


def test_hook_runtime_no_action():
    cats = _categorize_files(["teleclaude/hooks/receiver.py"])
    names = [c.name for c in cats]
    assert "hook runtime" in names
    hook_cat = next(c for c in cats if c.name == "hook runtime")
    assert hook_cat.instruction == ""


def test_tui_code_maps_to_sigusr2():
    cats = _categorize_files(["teleclaude/cli/tui/app.py"])
    names = [c.name for c in cats]
    assert "TUI code" in names


def test_telec_setup_maps_to_init():
    cats = _categorize_files(["teleclaude/project_setup/hooks.py"])
    names = [c.name for c in cats]
    assert "telec setup" in names


def test_agent_artifacts_maps_to_restart():
    cats = _categorize_files(["agents/skills/foo/SKILL.md"])
    names = [c.name for c in cats]
    assert "agent artifacts" in names
    category = next(c for c in cats if c.name == "agent artifacts")
    assert "curl -s --unix-socket /tmp/teleclaude-api.sock -X POST" in category.instruction
    assert category.instruction.startswith("Reload artifacts:")


def test_config_maps_to_restart():
    cats = _categorize_files(["config.yml"])
    names = [c.name for c in cats]
    assert "config" in names


def test_dependencies_maps_to_install():
    cats = _categorize_files(["pyproject.toml"])
    names = [c.name for c in cats]
    assert "dependencies" in names
    dep_cat = next(c for c in cats if c.name == "dependencies")
    assert dep_cat.instruction == "Install updated dependencies: `uv sync --extra test`"
    assert "uv sync" in dep_cat.evidence_substrings


def test_tests_only_maps_to_tests():
    cats = _categorize_files(["tests/unit/test_foo.py"])
    names = [c.name for c in cats]
    assert "tests only" in names


def test_mixed_source_and_tests_excludes_tests_only():
    cats = _categorize_files(["teleclaude/core/foo.py", "tests/unit/test_foo.py"])
    names = [c.name for c in cats]
    assert "daemon code" in names
    assert "tests only" not in names


def test_docs_only_returns_true():
    assert _is_docs_only(["docs/foo.md", "todos/bar.md", "README.md"]) is True


def test_docs_only_returns_false_for_code():
    assert _is_docs_only(["docs/foo.md", "teleclaude/core/foo.py"]) is False


def test_empty_diff_is_docs_only():
    assert _is_docs_only([]) is True


def test_get_uncommitted_files_normalizes_bare_repo(monkeypatch):
    calls: list[list[str]] = []
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="true\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="teleclaude/hooks/checkpoint.py\n", stderr=""),
        ]
    )

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return next(responses)

    monkeypatch.setattr("teleclaude.hooks.checkpoint.subprocess.run", _fake_run)

    files = _get_uncommitted_files("/repo")
    assert files == ["teleclaude/hooks/checkpoint.py"]
    assert calls == [
        ["git", "rev-parse", "--is-bare-repository"],
        ["git", "config", "--local", "core.bare", "false"],
        ["git", "diff", "--name-only", "HEAD"],
    ]


def test_get_uncommitted_files_retries_after_worktree_error(monkeypatch):
    calls: list[list[str]] = []
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="false\n", stderr=""),
            SimpleNamespace(returncode=128, stdout="", stderr="fatal: this operation must be run in a work tree"),
            SimpleNamespace(returncode=0, stdout="true\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="teleclaude/core/db.py\n", stderr=""),
        ]
    )

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return next(responses)

    monkeypatch.setattr("teleclaude.hooks.checkpoint.subprocess.run", _fake_run)

    files = _get_uncommitted_files("/repo")
    assert files == ["teleclaude/core/db.py"]
    assert calls == [
        ["git", "rev-parse", "--is-bare-repository"],
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "rev-parse", "--is-bare-repository"],
        ["git", "config", "--local", "core.bare", "false"],
        ["git", "diff", "--name-only", "HEAD"],
    ]


# ---------------------------------------------------------------------------
# Turn-local file scoping (false-positive guardrails)
# ---------------------------------------------------------------------------


def test_scope_git_files_no_mutation_signals_returns_empty():
    timeline = _timeline_with(
        _read_record("teleclaude/core/foo.py"),
        _bash_record("make status"),
    )
    scoped = _scope_git_files_to_current_turn(
        ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"],
        timeline,
        "/repo",
    )
    assert scoped == []


def test_scope_git_files_intersects_explicit_edit_paths():
    timeline = _timeline_with(
        _edit_record("teleclaude/core/foo.py"),
    )
    scoped = _scope_git_files_to_current_turn(
        ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"],
        timeline,
        "/repo",
    )
    assert scoped == ["teleclaude/core/foo.py"]


def test_scope_git_files_handles_absolute_edit_paths():
    timeline = _timeline_with(
        _edit_record("/repo/teleclaude/core/foo.py"),
    )
    scoped = _scope_git_files_to_current_turn(
        ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"],
        timeline,
        "/repo",
    )
    assert scoped == ["teleclaude/core/foo.py"]


def test_scope_git_files_shell_mutation_falls_back_to_git():
    timeline = _timeline_with(
        _bash_record("sed -i '' 's/a/b/' teleclaude/core/foo.py"),
    )
    scoped = _scope_git_files_to_current_turn(
        ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"],
        timeline,
        "/repo",
    )
    assert scoped == ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"]


def test_extract_turn_file_signals_detects_mutation_tools_and_bash():
    timeline = _timeline_with(
        ToolCallRecord(tool_name="Write", input_data={"file_path": "/repo/teleclaude/core/foo.py"}),
        _bash_record("apply_patch <<'PATCH'"),
    )
    touched, saw_mutation = _extract_turn_file_signals(timeline, "/repo")
    assert "teleclaude/core/foo.py" in touched
    assert saw_mutation is True


def test_extract_turn_file_signals_detects_exec_command_mutation():
    timeline = _timeline_with(
        ToolCallRecord(tool_name="exec_command", input_data={"command": "sed -i '' 's/a/b/' teleclaude/core/foo.py"}),
    )
    touched, saw_mutation = _extract_turn_file_signals(timeline, "/repo")
    assert touched == set()
    assert saw_mutation is True


def test_extract_turn_file_signals_detects_exec_command_mutation_via_cmd_key():
    timeline = _timeline_with(
        ToolCallRecord(tool_name="exec_command", input_data={"cmd": "sed -i '' 's/a/b/' teleclaude/core/foo.py"}),
    )
    touched, saw_mutation = _extract_turn_file_signals(timeline, "/repo")
    assert touched == set()
    assert saw_mutation is True


def test_extract_turn_file_signals_detects_namespaced_exec_command_mutation():
    timeline = _timeline_with(
        ToolCallRecord(
            tool_name="functions.exec_command", input_data={"cmd": "sed -i '' 's/a/b/' teleclaude/core/foo.py"}
        ),
    )
    touched, saw_mutation = _extract_turn_file_signals(timeline, "/repo")
    assert touched == set()
    assert saw_mutation is True


def test_extract_turn_file_signals_extracts_apply_patch_paths():
    timeline = _timeline_with(
        ToolCallRecord(
            tool_name="apply_patch",
            input_data={
                "input": "*** Begin Patch\n*** Update File: /repo/teleclaude/core/foo.py\n*** End Patch\n",
            },
        ),
    )
    touched, saw_mutation = _extract_turn_file_signals(timeline, "/repo")
    assert "teleclaude/core/foo.py" in touched
    assert saw_mutation is True


def test_command_likely_mutates_files_ignores_non_mutating_commands():
    assert _command_likely_mutates_files("make status") is False
    assert _command_likely_mutates_files("instrukt-ai-logs teleclaude --since 2m") is False


# ---------------------------------------------------------------------------
# Evidence checking (R4)
# ---------------------------------------------------------------------------


def test_has_evidence_found():
    timeline = _timeline_with(_bash_record("make restart"))
    assert _has_evidence(timeline, ["make restart"]) is True


def test_has_evidence_not_found():
    timeline = _timeline_with(_bash_record("echo hello"))
    assert _has_evidence(timeline, ["make restart"]) is False


def test_has_evidence_empty_timeline():
    assert _has_evidence(_empty_timeline(), ["make restart"]) is False


def test_has_evidence_ignores_failed_commands():
    timeline = _timeline_with(_bash_record("make restart", had_error=True))
    assert _has_evidence(timeline, ["make restart"]) is False


def test_has_evidence_ignores_literal_mentions():
    timeline = _timeline_with(
        _bash_record("echo \"Run pkill -SIGUSR2 -f -- '-m teleclaude.cli.telec$'\""),
    )
    assert _has_evidence(timeline, ["pkill -SIGUSR2"]) is False


# ---------------------------------------------------------------------------
# Verification gap detection (R4 integration)
# ---------------------------------------------------------------------------


def test_restart_suppressed_when_make_restart_in_transcript():
    timeline = _timeline_with(
        _bash_record("make restart"),
        _bash_record("make status"),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    # Restart instruction should be suppressed
    assert not any("make restart" in a.lower() for a in result.required_actions)


def test_restart_suppressed_when_exec_command_uses_cmd_key():
    timeline = _timeline_with(
        ToolCallRecord(tool_name="exec_command", input_data={"cmd": "make restart"}),
        ToolCallRecord(tool_name="exec_command", input_data={"cmd": "make status"}),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert not any("make restart" in a.lower() for a in result.required_actions)


def test_restart_not_suppressed_when_absent():
    timeline = _timeline_with(_bash_record("echo hello"))
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert any("restart" in a.lower() for a in result.required_actions)


def test_restart_not_suppressed_when_make_restart_failed():
    timeline = _timeline_with(
        _bash_record("make restart", had_error=True),
        _bash_record("make status"),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert any("restart" in a.lower() for a in result.required_actions)


def test_make_status_required_when_status_failed():
    timeline = _timeline_with(
        _bash_record("make restart"),
        _bash_record("make status", had_error=True),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert any("make status" in a.lower() for a in result.required_actions)


def test_sigusr2_suppressed_when_pkill_in_transcript():
    timeline = _timeline_with(_bash_record("pkill -SIGUSR2 -f teleclaude"))
    result = run_heuristics(
        ["teleclaude/cli/tui/app.py"],
        timeline,
        _default_context(),
    )
    assert not any("SIGUSR2" in a for a in result.required_actions)


def test_agent_restart_suppressed_when_api_restart_call_seen():
    timeline = _timeline_with(
        _bash_record(
            'curl --unix-socket /tmp/teleclaude-api.sock -X POST "http://localhost/sessions/abc/agent-restart"'
        ),
    )
    result = run_heuristics(
        ["agents/commands/next-work.md"],
        timeline,
        _default_context(),
    )
    assert not any("agent-restart" in a.lower() for a in result.required_actions)


def test_log_check_suppressed_when_instrukt_ai_logs_in_transcript():
    timeline = _timeline_with(
        _bash_record("make restart"),
        _bash_record("make status"),
        _bash_record("instrukt-ai-logs teleclaude --since 2m"),
        _bash_record("pytest tests/"),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert not any("instrukt-ai-logs" in a for a in result.required_actions)


def test_hook_runtime_only_requires_log_check_when_missing():
    result = run_heuristics(
        ["teleclaude/hooks/receiver.py"],
        _empty_timeline(),
        _default_context(),
    )
    assert any("instrukt-ai-logs" in action for action in result.required_actions)


def test_test_instruction_suppressed_when_pytest_in_transcript():
    timeline = _timeline_with(
        _bash_record("make restart"),
        _bash_record("make status"),
        _bash_record("pytest tests/unit/test_foo.py"),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert not any("test" in a.lower() and "run" in a.lower() for a in result.required_actions)


def test_mixed_source_and_tests_no_duplicate_test_actions():
    result = run_heuristics(
        ["teleclaude/core/foo.py", "tests/unit/test_foo.py"],
        _empty_timeline(),
        _default_context(),
    )
    test_actions = [a for a in result.required_actions if "test" in a.lower()]
    assert len(test_actions) == 1


def test_daemon_and_config_emit_single_restart_action():
    result = run_heuristics(
        ["teleclaude/core/foo.py", "config.yml"],
        _empty_timeline(),
        _default_context(),
    )
    restart_actions = [action for action in result.required_actions if "make restart" in action]
    assert len(restart_actions) == 1


def test_tests_plus_docs_still_requires_tests_action():
    result = run_heuristics(
        ["tests/unit/test_foo.py", "docs/notes.md"],
        _empty_timeline(),
        _default_context(),
    )
    assert any("test" in action.lower() for action in result.required_actions)


def test_all_suppressed_emits_all_clear():
    timeline = _timeline_with(
        _bash_record("make restart"),
        _bash_record("make status"),
        _bash_record("instrukt-ai-logs teleclaude --since 2m"),
        _bash_record("pytest tests/"),
    )
    result = run_heuristics(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert result.is_all_clear is True


# ---------------------------------------------------------------------------
# Error state — Layer 1 gate (R5)
# ---------------------------------------------------------------------------


def test_is_error_false_never_triggers_observation():
    """Successful command with tracebacks in output should be silent."""
    timeline = _timeline_with(
        _bash_record(
            "instrukt-ai-logs teleclaude",
            had_error=False,
            result_snippet="Traceback (most recent call last):\n  SyntaxError",
        ),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_is_error_true_unresolved_emits_observation():
    """Failed tool call with no follow-up emits observation."""
    timeline = _timeline_with(
        _bash_record("pytest tests/", had_error=True, result_snippet="FAILED"),
    )
    observations = _check_error_state(timeline)
    assert len(observations) == 1


def test_is_error_resolved_by_bash_retry_suppressed():
    """Failed then same Bash command re-run is suppressed."""
    timeline = _timeline_with(
        _bash_record("pytest tests/", had_error=True, result_snippet="FAILED"),
        _bash_record("pytest tests/", had_error=False, result_snippet="PASSED"),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_is_error_resolved_by_edit_suppressed():
    """Failed then Edit targeting same file path is suppressed."""
    timeline = _timeline_with(
        ToolCallRecord(
            tool_name="Bash",
            input_data={"command": "python /tmp/foo.py", "file_path": "/tmp/foo.py"},
            had_error=True,
            result_snippet="SyntaxError",
        ),
        _edit_record("/tmp/foo.py"),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_is_error_resolved_by_command_rerun_suppressed():
    """pytest fails, then pytest runs again is suppressed."""
    timeline = _timeline_with(
        _bash_record("make test", had_error=True, result_snippet="FAILED 2"),
        _bash_record("make test", had_error=False, result_snippet="passed"),
    )
    observations = _check_error_state(timeline)
    assert observations == []


# ---------------------------------------------------------------------------
# Error state — Layer 2 enrichment (R5)
# ---------------------------------------------------------------------------


def test_enrichment_traceback_pattern():
    record = _bash_record("python foo.py", had_error=True, result_snippet="Traceback (most recent call last):\n...")
    msg = _enrich_error(record)
    assert "Python errors" in msg


def test_enrichment_syntax_error():
    record = _bash_record("python foo.py", had_error=True, result_snippet="SyntaxError: invalid syntax")
    msg = _enrich_error(record)
    assert "Syntax errors" in msg


def test_enrichment_import_error():
    record = _bash_record("python foo.py", had_error=True, result_snippet="ImportError: No module named 'foo'")
    msg = _enrich_error(record)
    assert "Import errors" in msg


def test_enrichment_pytest_failure():
    record = _bash_record("pytest tests/", had_error=True, result_snippet="FAILED test_foo")
    msg = _enrich_error(record)
    assert "Test failures" in msg


def test_enrichment_unknown_error():
    record = _bash_record("some-tool", had_error=True, result_snippet="weird error")
    msg = _enrich_error(record)
    assert "command returned errors" in msg


def test_enrichment_does_not_treat_test_mentions_as_test_commands():
    record = _bash_record("echo pytest tests/unit/test_foo.py", had_error=True, result_snippet="error")
    msg = _enrich_error(record)
    assert "command returned errors" in msg


def test_enrichment_only_fires_when_layer1_fires():
    """Successful command with SyntaxError in stdout should have no observations."""
    timeline = _timeline_with(
        _bash_record(
            "grep SyntaxError output.log",
            had_error=False,
            result_snippet="SyntaxError: found in old log",
        ),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_search_no_matches_exit_code_is_non_actionable():
    """`rg`/`grep` exit code 1 for no matches should not create checkpoint noise."""
    timeline = _timeline_with(
        _bash_record(
            "rg -n no_such_token tests/unit",
            had_error=True,
            result_snippet="Process exited with code 1\nOutput:\n",
        ),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_search_no_matches_uv_run_rg_is_non_actionable():
    timeline = _timeline_with(
        _bash_record(
            "uv run rg -n no_such_token tests/unit",
            had_error=True,
            result_snippet="Process exited with code 1\nOutput:\n",
        ),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_search_error_exit_code_with_path_issue_is_actionable():
    """Path/permission problems should still surface as actionable errors."""
    timeline = _timeline_with(
        _bash_record(
            "rg -n token missing/path",
            had_error=True,
            result_snippet="Process exited with code 1\nNo such file or directory\n",
        ),
    )
    observations = _check_error_state(timeline)
    assert len(observations) == 1


# ---------------------------------------------------------------------------
# Error state — workflow scenarios
# ---------------------------------------------------------------------------


def test_test_fix_test_cycle_is_silent():
    """pytest fail → edit → pytest pass → stop: nothing fires."""
    timeline = _timeline_with(
        _bash_record("pytest tests/", had_error=True, result_snippet="FAILED"),
        _edit_record("/tmp/foo.py"),
        _bash_record("pytest tests/", had_error=False, result_snippet="PASSED"),
    )
    observations = _check_error_state(timeline)
    assert observations == []


def test_partial_fix_still_fires():
    """Second pytest also fails → observation fires."""
    timeline = _timeline_with(
        _bash_record("pytest tests/", had_error=True, result_snippet="FAILED 3"),
        _edit_record("/tmp/foo.py"),
        _bash_record("pytest tests/", had_error=True, result_snippet="FAILED 1"),
    )
    observations = _check_error_state(timeline)
    # First error resolved by re-run, second error unresolved
    assert len(observations) == 1


def test_run_heuristics_dedupes_duplicate_error_observations():
    timeline = _timeline_with(
        _bash_record("foo-cmd", had_error=True, result_snippet="error one"),
        _bash_record("bar-cmd", had_error=True, result_snippet="error two"),
    )
    result = run_heuristics(["teleclaude/core/foo.py"], timeline, _default_context())
    generic = "A command returned errors — verify the issue is resolved"
    assert result.observations.count(generic) == 1


def test_duplicate_failed_commands_keep_later_unresolved_error():
    """Duplicate failed command values should not alias to the first record."""
    timeline = _timeline_with(
        _bash_record("pytest tests/unit/test_alpha.py", had_error=True, result_snippet="FAILED"),
        _bash_record("pytest tests/unit/test_alpha.py", had_error=True, result_snippet="FAILED"),
        _edit_record("/tmp/alpha.py"),
    )
    observations = _check_error_state(timeline)
    assert len(observations) == 1


def test_error_not_resolved_by_different_pytest_command():
    """Different pytest target should not suppress unresolved original failure."""
    timeline = _timeline_with(
        _bash_record("pytest tests/unit/test_alpha.py", had_error=True, result_snippet="FAILED"),
        _bash_record("pytest tests/unit/test_beta.py", had_error=False, result_snippet="PASSED"),
    )
    observations = _check_error_state(timeline)
    assert len(observations) == 1


# ---------------------------------------------------------------------------
# Edit hygiene (R6)
# ---------------------------------------------------------------------------


def test_edit_without_read_emits_observation():
    timeline = _timeline_with(_edit_record("/tmp/foo.py"))
    observations = _check_edit_hygiene(timeline, [])
    assert any("read first" in o.lower() for o in observations)


def test_edit_with_read_suppressed():
    timeline = _timeline_with(
        _read_record("/tmp/foo.py"),
        _edit_record("/tmp/foo.py"),
    )
    observations = _check_edit_hygiene(timeline, [])
    assert not any("read first" in o.lower() for o in observations)


def test_wide_blast_radius_emits_observation():
    git_files = [
        "teleclaude/core/foo.py",
        "tests/unit/test_foo.py",
        "docs/design/arch.md",
        "tools/lint/check.py",
    ]
    observations = _check_edit_hygiene(_empty_timeline(), git_files)
    assert any("subsystems" in o.lower() for o in observations)


def test_narrow_blast_radius_suppressed():
    git_files = [
        "teleclaude/core/foo.py",
        "teleclaude/core/bar.py",
    ]
    observations = _check_edit_hygiene(_empty_timeline(), git_files)
    assert not any("subsystems" in o.lower() for o in observations)


# ---------------------------------------------------------------------------
# Working slug alignment (R7)
# ---------------------------------------------------------------------------


def test_no_slug_skips_check():
    observations = _check_slug_alignment(["teleclaude/core/foo.py"], _default_context())
    assert observations == []


def test_missing_plan_skips_check(tmp_path):
    ctx = _default_context(project_path=str(tmp_path), working_slug="nonexistent-slug")
    observations = _check_slug_alignment(["teleclaude/core/foo.py"], ctx)
    assert observations == []


def test_slug_drift_emits_observation(tmp_path):
    # Create a plan that expects changes in different files
    slug_dir = tmp_path / "todos" / "my-slug"
    slug_dir.mkdir(parents=True)
    plan = slug_dir / "implementation-plan.md"
    plan.write_text(
        "## Files to Change\n\n| File | Change |\n| --- | --- |\n| `teleclaude/other/module.py` | Modify |\n",
        encoding="utf-8",
    )
    ctx = _default_context(project_path=str(tmp_path), working_slug="my-slug")
    observations = _check_slug_alignment(["teleclaude/core/foo.py"], ctx)
    assert any("right task" in o.lower() for o in observations)


def test_slug_partial_overlap_suppressed(tmp_path):
    slug_dir = tmp_path / "todos" / "my-slug"
    slug_dir.mkdir(parents=True)
    plan = slug_dir / "implementation-plan.md"
    plan.write_text(
        "## Files to Change\n\n| File | Change |\n| --- | --- |\n| `teleclaude/core/foo.py` | Modify |\n",
        encoding="utf-8",
    )
    ctx = _default_context(project_path=str(tmp_path), working_slug="my-slug")
    observations = _check_slug_alignment(["teleclaude/core/foo.py"], ctx)
    assert observations == []


def test_slug_overlap_ignores_new_annotation_in_plan(tmp_path):
    slug_dir = tmp_path / "todos" / "my-slug"
    slug_dir.mkdir(parents=True)
    plan = slug_dir / "implementation-plan.md"
    plan.write_text(
        "## Files to Change\n\n| File | Change |\n| --- | --- |\n| `teleclaude/core/foo.py` (NEW) | Add |\n",
        encoding="utf-8",
    )
    ctx = _default_context(project_path=str(tmp_path), working_slug="my-slug")
    observations = _check_slug_alignment(["teleclaude/core/foo.py"], ctx)
    assert observations == []


# ---------------------------------------------------------------------------
# Message composition (R9)
# ---------------------------------------------------------------------------


def test_docs_only_message():
    msg = build_checkpoint_message(["docs/foo.md"], _empty_timeline(), _default_context())
    assert msg.startswith("[TeleClaude Checkpoint] - ")
    assert "No code changes" in msg
    assert "telec sync" in msg


def test_empty_diff_message():
    msg = build_checkpoint_message([], _empty_timeline(), _default_context())
    assert msg.startswith("[TeleClaude Checkpoint] - ")
    assert "No code changes" in msg
    assert "telec sync" in msg


def test_all_clear_message_is_minimal():
    timeline = _timeline_with(
        _bash_record("make restart"),
        _bash_record("make status"),
        _bash_record("instrukt-ai-logs teleclaude --since 2m"),
        _bash_record("pytest tests/"),
    )
    msg = build_checkpoint_message(
        ["teleclaude/core/foo.py"],
        timeline,
        _default_context(),
    )
    assert msg.startswith("[TeleClaude Checkpoint] - ")
    assert "All expected" in msg
    assert "Docs check" in msg


def test_message_has_required_actions():
    msg = build_checkpoint_message(
        ["teleclaude/core/foo.py"],
        _empty_timeline(),
        _default_context(),
    )
    assert msg.startswith("[TeleClaude Checkpoint] - ")
    assert "Required actions:" in msg
    assert "1." in msg
    assert "Docs check" in msg


def test_message_uses_supplied_log_window():
    msg = build_checkpoint_message(
        ["teleclaude/core/foo.py"],
        _empty_timeline(),
        _default_context(),
        log_since_window="9m",
    )
    assert "instrukt-ai-logs teleclaude --since 9m" in msg


def test_message_action_precedence_is_deterministic():
    """Actions follow fixed order based on category precedence."""
    msg = build_checkpoint_message(
        ["pyproject.toml", "teleclaude/core/foo.py"],
        _empty_timeline(),
        _default_context(),
    )
    lines = msg.splitlines()
    action_lines = [line for line in lines if line.strip().startswith(("1.", "2.", "3.", "4.", "5."))]
    # Dependencies (precedence 20) before daemon code (precedence 30)
    dep_idx = next((i for i, line in enumerate(action_lines) if "uv sync" in line.lower()), None)
    restart_idx = next((i for i, line in enumerate(action_lines) if "restart" in line.lower()), None)
    if dep_idx is not None and restart_idx is not None:
        assert dep_idx < restart_idx


def test_message_observations_separate_from_actions():
    msg = build_checkpoint_message(
        ["teleclaude/core/foo.py"],
        _empty_timeline(),
        _default_context(),
    )
    if "Observations:" in msg:
        obs_idx = msg.index("Observations:")
        actions_idx = msg.index("Required actions:")
        assert obs_idx > actions_idx


def test_get_checkpoint_content_suppresses_stale_dirty_files(monkeypatch):
    """Repo-wide stale dirty files should not force turn-local restart actions."""
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._is_checkpoint_project_supported",
        lambda _project: True,
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._get_uncommitted_files",
        lambda _project: ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"],
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint.extract_tool_calls_current_turn",
        lambda _path, _agent, **_kw: _timeline_with(
            _read_record("README.md"),
            _bash_record("make status"),
        ),
    )

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path="/repo",
    )
    assert msg is None


def test_get_checkpoint_content_session_fallback_catches_earlier_turn_edits(monkeypatch):
    """When current turn has no edits but full session does, fallback should fire."""
    call_log: list[bool] = []

    def _mock_extract(_path, _agent, *, full_session=False):
        call_log.append(full_session)
        if full_session:
            # Full session has the edit from an earlier turn
            return _timeline_with(_edit_record("teleclaude/core/foo.py"))
        # Current turn only has reads (user message shifted the boundary)
        return _timeline_with(_read_record("README.md"))

    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._is_checkpoint_project_supported",
        lambda _project: True,
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._get_uncommitted_files",
        lambda _project: ["teleclaude/core/foo.py"],
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint.extract_tool_calls_current_turn",
        _mock_extract,
    )

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path="/repo",
    )
    assert msg is not None
    assert "Run `make restart`" in msg
    # Should have been called twice: first current-turn, then full-session fallback
    assert call_log == [False, True]


def test_get_checkpoint_content_keeps_actions_for_turn_local_edits(monkeypatch):
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._is_checkpoint_project_supported",
        lambda _project: True,
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._get_uncommitted_files",
        lambda _project: ["teleclaude/core/foo.py", "teleclaude/cli/tui/app.py"],
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint.extract_tool_calls_current_turn",
        lambda _path, _agent, **_kw: _timeline_with(
            _edit_record("teleclaude/core/foo.py"),
        ),
    )

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path="/repo",
    )
    assert "Run `make restart`" in msg


def test_get_checkpoint_content_keeps_actions_for_exec_command_cmd_mutation(monkeypatch):
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._is_checkpoint_project_supported",
        lambda _project: True,
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._get_uncommitted_files",
        lambda _project: ["teleclaude/core/foo.py"],
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint.extract_tool_calls_current_turn",
        lambda _path, _agent, **_kw: _timeline_with(
            ToolCallRecord(tool_name="exec_command", input_data={"cmd": "apply_patch <<'PATCH'"}),
        ),
    )

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path="/repo",
    )
    assert msg is not None
    assert "Run `make restart`" in msg


def test_get_checkpoint_content_derives_log_window_from_elapsed(monkeypatch):
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._is_checkpoint_project_supported",
        lambda _project: True,
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._get_uncommitted_files",
        lambda _project: ["teleclaude/core/foo.py"],
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint.extract_tool_calls_current_turn",
        lambda _path, _agent, **_kw: _timeline_with(
            _edit_record("teleclaude/core/foo.py"),
            _bash_record("make restart"),
            _bash_record("make status"),
        ),
    )

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path="/repo",
        elapsed_since_turn_start_s=601.0,
    )
    assert msg is not None
    assert "instrukt-ai-logs teleclaude --since 11m" in msg


def test_get_checkpoint_content_returns_none_for_docs_only_changes(monkeypatch):
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._is_checkpoint_project_supported",
        lambda _project: True,
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint._get_uncommitted_files",
        lambda _project: ["docs/notes.md"],
    )
    monkeypatch.setattr(
        "teleclaude.hooks.checkpoint.extract_tool_calls_current_turn",
        lambda _path, _agent, **_kw: _timeline_with(
            _edit_record("docs/notes.md"),
        ),
    )

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path="/repo",
    )
    assert msg is None


def test_get_checkpoint_content_skips_out_of_scope_project(monkeypatch, tmp_path):
    """Non-TeleClaude projects should not receive checkpoint injections."""

    def _unexpected_git_call(_project: str):
        raise AssertionError("git diff should not be called for out-of-scope projects")

    monkeypatch.setattr("teleclaude.hooks.checkpoint._get_uncommitted_files", _unexpected_git_call)

    msg = get_checkpoint_content(
        transcript_path="/tmp/fake.jsonl",
        agent_name=AgentName.CLAUDE,
        project_path=str(tmp_path),
    )
    assert msg is None

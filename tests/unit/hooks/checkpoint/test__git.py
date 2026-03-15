"""Characterization tests for teleclaude.hooks.checkpoint._git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from teleclaude.hooks.checkpoint import _git
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline


def _completed_process(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestCheckpointProjectSupport:
    @pytest.mark.unit
    def test_requires_checkpoint_marker_and_next_work_command(self, tmp_path: Path) -> None:
        (tmp_path / "teleclaude" / "hooks" / "checkpoint").mkdir(parents=True)
        (tmp_path / "teleclaude" / "hooks" / "checkpoint" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "agents" / "commands").mkdir(parents=True)
        (tmp_path / "agents" / "commands" / "next-work.md").write_text("", encoding="utf-8")

        assert _git._is_checkpoint_project_supported(str(tmp_path)) is True
        assert _git._is_checkpoint_project_supported(str(tmp_path / "missing")) is False


class TestGitDiffHelpers:
    @pytest.mark.unit
    def test_get_uncommitted_files_retries_after_normalizing_a_bare_repository(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        responses = iter(
            [
                _completed_process(stdout="true\n"),
                _completed_process(),
                _completed_process(returncode=128, stderr="fatal: this operation must be run in a work tree"),
                _completed_process(stdout="true\n"),
                _completed_process(),
                _completed_process(stdout="teleclaude/hooks/inbound.py\ntests/unit/hooks/test_inbound.py\n"),
            ]
        )

        def _run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return next(responses)

        monkeypatch.setattr(_git.subprocess, "run", _run)

        assert _git._get_uncommitted_files("/repo") == [
            "teleclaude/hooks/inbound.py",
            "tests/unit/hooks/test_inbound.py",
        ]

    @pytest.mark.unit
    def test_extract_shell_and_apply_patch_paths_normalize_project_relative_files(self) -> None:
        command_paths = _git._extract_shell_touched_paths(
            "python -m pytest ./tests/unit/hooks/test_inbound.py teleclaude/hooks/inbound.py",
            "/repo",
        )
        patch_paths = _git._extract_apply_patch_paths(
            "*** Begin Patch\n*** Update File: /repo/teleclaude/hooks/inbound.py\n"
            "*** Add File: tests/unit/hooks/test_inbound.py\n*** End Patch\n",
            "/repo",
        )

        assert command_paths == {"tests/unit/hooks/test_inbound.py", "teleclaude/hooks/inbound.py"}
        assert patch_paths == {"tests/unit/hooks/test_inbound.py", "teleclaude/hooks/inbound.py"}

    @pytest.mark.unit
    def test_scope_git_files_to_current_turn_uses_only_turn_local_file_signals(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                ToolCallRecord(tool_name="functions.exec_command", input_data={"cmd": "touch docs/guide.md"}),
                ToolCallRecord(
                    tool_name="apply_patch", input_data={"input": "*** Add File: tests/unit/hooks/test_git.py"}
                ),
            ]
        )
        git_files = ["README.md", "docs/guide.md", "tests/unit/hooks/test_git.py"]

        touched_files, saw_mutation = _git._extract_turn_file_signals(timeline, "/repo")
        scoped = _git._scope_git_files_to_current_turn(git_files, timeline, "/repo")

        assert touched_files == {"docs/guide.md", "tests/unit/hooks/test_git.py"}
        assert saw_mutation is True
        assert scoped == ["docs/guide.md", "tests/unit/hooks/test_git.py"]

    @pytest.mark.unit
    def test_categorize_files_marks_test_only_diffs_and_docs_only_files(self) -> None:
        categories = _git._categorize_files(["tests/unit/hooks/test_inbound.py"])

        assert _git._is_docs_only(["todos/chartest-hooks/demo.md"]) is True
        assert "tests only" in [category.name for category in categories]

    @pytest.mark.unit
    def test_canonical_tool_name_keeps_only_the_terminal_tool_suffix(self) -> None:
        assert _git._canonical_tool_name("functions.exec_command") == "exec_command"
        assert _git._canonical_tool_name("  APPLY_PATCH  ") == "apply_patch"

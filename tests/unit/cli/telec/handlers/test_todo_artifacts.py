"""Tests for telec todo artifacts {list|read|write} and telec todo stamp."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts, _handle_todo_stamp, handle_mark_phase
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase

_MODULE = "teleclaude.cli.telec.handlers.todo"


class TestHandleTodoArtifactsList:
    """telec todo artifacts list <slug>."""

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["list"])

    def test_lists_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"artifacts": ["input", "requirements"]}):
            _handle_todo_artifacts(["list", "my-slug"])

        output = capsys.readouterr().out
        assert "input" in output
        assert "requirements" in output


class TestHandleTodoArtifactsRead:
    """telec todo artifacts read <slug> <name>."""

    def test_missing_args_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["read", "my-slug"])

    def test_prints_content(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"content": "artifact-content"}):
            _handle_todo_artifacts(["read", "my-slug", "requirements"])

        assert "artifact-content" in capsys.readouterr().out


class TestHandleTodoArtifactsWrite:
    """telec todo artifacts write <slug> <name> <content>."""

    def test_missing_args_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["write", "my-slug"])

    def test_writes_inline_content(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_head_commit", return_value="head-sha"),
            patch(f"{_MODULE}.extract_referenced_paths", return_value=["src/app.py"]),
        ):
            _handle_todo_artifacts(["write", "my-slug", "requirements", "inline-content"])

        mock_api.assert_called_once()
        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["content"] == "inline-content"
        assert body["codebase_sha_at_write"] == "head-sha"
        assert body["referenced_paths"] == ["src/app.py"]


class TestHandleTodoArtifactsDiff:
    """telec todo artifacts diff <slug> <name> <old-digest> <new-digest>."""

    def test_missing_args_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["diff", "my-slug", "requirements", "abc123"])

    def test_prints_diff_from_api(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"diff": "@@ -1 +1 @@\n-old\n+new\n"}):
            _handle_todo_artifacts(["diff", "my-slug", "requirements", "abc123", "def456"])

        assert "+new" in capsys.readouterr().out

    def test_passes_digests_as_query_params(self) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"diff": ""}) as mock_api:
            _handle_todo_artifacts(["diff", "my-slug", "requirements", "abc123", "def456"])

        kwargs = mock_api.call_args.kwargs
        params = kwargs.get("params", {})
        assert params.get("old") == "abc123"
        assert params.get("new") == "def456"
        assert "cwd" in params


class TestHandleTodoStamp:
    """telec todo stamp <slug> --verdict approve."""

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_stamp([])

    def test_verdict_stamp(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--verdict", "approve", "--phase", "architecture_review"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="verdict",
            value="approve",
            phase="architecture_review",
            caller_session_id="sess-1",
        )

    def test_prd_approved_stamp(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--prd-approved"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="prd_approved",
            value="true",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_plan_approved_stamp(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--plan-approved"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="plan_approved",
            value="true",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_build_complete_stamp(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="builder-session"),
        ):
            _handle_todo_stamp(["my-slug", "--build-complete"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="build_complete",
            value="true",
            phase=None,
            caller_session_id="builder-session",
        )

    def test_build_started_flag_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_stamp(["my-slug", "--build-started"])

        assert "machine-owned" in capsys.readouterr().out


class TestHandleMarkPhase:
    """telec todo mark-phase <slug> --phase <value>."""

    def test_prepare_phase_value_writes_lifecycle_phase_field(self) -> None:
        with patch(
            f"{_MODULE}.mark_phase_state",
            return_value={"lifecycle_phase": PreparePhase.PREPARED.value, "kind": "todo"},
        ) as mock_mark:
            exit_code = handle_mark_phase(slug="my-slug", phase=PreparePhase.PREPARED.value, cwd="/tmp/cwd")

        assert exit_code == 0
        mock_mark.assert_called_once_with("/tmp/cwd", "my-slug", PreparePhase.PREPARED.value)

    def test_work_phase_value_writes_lifecycle_phase_field(self) -> None:
        with patch(
            f"{_MODULE}.mark_phase_state",
            return_value={"lifecycle_phase": WorkPhase.BUILD_STARTED.value},
        ) as mock_mark:
            exit_code = handle_mark_phase(slug="my-slug", phase=WorkPhase.BUILD_STARTED.value, cwd="/tmp/cwd")

        assert exit_code == 0
        mock_mark.assert_called_once_with("/tmp/cwd", "my-slug", WorkPhase.BUILD_STARTED.value)

    def test_unknown_phase_value_rejected_with_listing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Unknown values exit non-zero, do not write, and list both enums' values."""
        with patch(f"{_MODULE}.mark_phase_state") as mock_mark:
            exit_code = handle_mark_phase(slug="my-slug", phase="not_a_real_phase", cwd="/tmp/cwd")

        assert exit_code != 0
        mock_mark.assert_not_called()
        combined = capsys.readouterr().err
        assert PreparePhase.PREPARED.value in combined
        assert WorkPhase.BUILD_STARTED.value in combined

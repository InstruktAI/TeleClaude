# guard: no-companion
"""Tests for telec todo artifacts {list|read|write} and telec todo stamp."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts, _handle_todo_stamp, handle_mark_phase
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.types.state_value import StateValue

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
        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
            _handle_todo_artifacts(["write", "my-slug", "requirements", "inline-content"])

        mock_api.assert_called_once()
        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["content"] == "inline-content"


class TestHandleTodoStamp:
    """telec todo stamp <slug> --verdict approve."""

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_stamp([])

    def test_verdict_stamp(self) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
            _handle_todo_stamp(["my-slug", "--verdict", "approve", "--phase", "requirements_review"])

        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["stamp_type"] == "verdict"
        assert body["value"] == "approve"
        assert body["phase"] == "requirements_review"

    def test_removed_automation_flag_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_stamp(["my-slug", "--requirements-ready"])

        assert "Removed automation-only stamp flag" in capsys.readouterr().out


class TestHandleMarkPhase:
    """telec todo mark-phase <slug> --phase <value>."""

    def _prepared_state(self) -> dict[str, StateValue]:
        return {
            "requirements_review": {"verdict": "approve"},
            "artifacts": {
                "requirements": {"produced_at": "2026-01-01T00:00:00+00:00"},
                "test_specs": {"produced_at": "2026-01-01T00:00:00+00:00"},
                "implementation_plan": {"produced_at": "2026-01-01T00:00:00+00:00"},
            },
            "test_spec_review": {"verdict": "approve"},
            "plan_review": {"verdict": "approve"},
            "dor": {"score": 8, "status": "pass"},
            "grounding": {"valid": True},
            "lifecycle_phase": "prepared",
            "kind": "todo",
        }

    def test_prepare_phase_value_writes_lifecycle_phase_field(self) -> None:
        captured: dict[str, StateValue] = {}

        def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
            captured["state"] = dict(state)

        with (
            patch(f"{_MODULE}.write_phase_state", _fake_write),
            patch(f"{_MODULE}.read_phase_state", return_value=self._prepared_state()),
        ):
            exit_code = handle_mark_phase(slug="my-slug", phase=PreparePhase.PREPARED.value, cwd="/tmp/cwd")

        assert exit_code == 0
        persisted = captured.get("state", {})
        assert isinstance(persisted, dict)
        assert persisted.get("lifecycle_phase") == PreparePhase.PREPARED.value
        assert persisted.get("kind") == "todo"

    def test_work_phase_value_writes_lifecycle_phase_field(self) -> None:
        captured: dict[str, StateValue] = {}

        def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
            captured["state"] = dict(state)

        with (
            patch(f"{_MODULE}.write_phase_state", _fake_write),
            patch(f"{_MODULE}.read_phase_state", return_value=self._prepared_state()),
        ):
            exit_code = handle_mark_phase(slug="my-slug", phase=WorkPhase.BUILD_STARTED.value, cwd="/tmp/cwd")

        assert exit_code == 0
        persisted = captured.get("state", {})
        assert isinstance(persisted, dict)
        assert persisted.get("lifecycle_phase") == WorkPhase.BUILD_STARTED.value

    def test_unknown_phase_value_rejected_with_listing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Unknown values exit non-zero, do not write, and list both enums' values."""
        write_calls: list[tuple[str, str, dict[str, StateValue]]] = []

        def _recording_write(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
            write_calls.append((cwd, slug, dict(state)))

        with patch(f"{_MODULE}.write_phase_state", _recording_write):
            exit_code = handle_mark_phase(slug="my-slug", phase="not_a_real_phase", cwd="/tmp/cwd")

        assert exit_code != 0
        assert write_calls == []
        combined = capsys.readouterr().err
        assert PreparePhase.PREPARED.value in combined
        assert WorkPhase.BUILD_STARTED.value in combined

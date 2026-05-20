"""Tests for telec todo dump/remove/split CLI handlers (DB-backed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.handlers.todo import (
    _handle_todo_create,
    _handle_todo_design,
    _handle_todo_dump,
    _handle_todo_reconcile,
    _handle_todo_remove,
    _handle_todo_rename,
    _handle_todo_split,
    _handle_todo_stamp,
)

_MODULE = "teleclaude.cli.telec.handlers.todo"
_RENAME_RESULT = "renamed old-slug->new-slug (todos.db, delivered_by:1, worktree)"


class TestHandleTodoDump:
    """telec todo dump <slug> <content>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}),
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "my content"])

        assert "Dumped todo: my-slug" in capsys.readouterr().out

    def test_missing_args_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_dump(["only-slug"])

    def test_passes_after_deps(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "content", "--after", "dep-a,dep-b"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["after"] == ["dep-a", "dep-b"]

    def test_draft_skips_event_emission(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
        ):
            _handle_todo_dump(["my-slug", "content", "--draft"])

        # Only the POST /todos/dump call, no /events/emit call
        assert mock_api.call_count == 1
        assert mock_api.call_args_list[0][0][1] == "/todos/dump"

    def test_draft_sends_kind_draft(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
        ):
            _handle_todo_dump(["my-slug", "content", "--draft"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["kind"] == "draft"

    def test_prepped_sends_kind_prepped(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "plan content", "--prepped"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["kind"] == "prepped"

    def test_prepped_still_emits_dumped_event(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "plan content", "--prepped"])

        # The dumped event must fire regardless of kind — subscribers (notifications,
        # dashboards, other cartridges) decide whether to act on it.
        paths = [call[0][1] for call in mock_api.call_args_list]
        assert "/todos/dump" in paths
        assert "/events/emit" in paths

    def test_prepped_defaults_kind_to_null_when_flag_absent(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "content"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["kind"] is None

    def test_prepped_confirmation_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}),
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "plan content", "--prepped"])

        out = capsys.readouterr().out
        assert "Dumped todo: my-slug" in out
        assert "prepped" in out


class TestHandleTodoCreate:
    """telec todo create <slug>."""

    def test_success_prints_confirmation(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(f"{_MODULE}.create_draft_skeleton", return_value="Todo created: my-slug") as mock_create:
            _handle_todo_create(["my-slug"])

        assert "Todo created: my-slug" in capsys.readouterr().out
        mock_create.assert_called_once_with("/repo", "my-slug", after=None, kind="feature")

    def test_passes_after_deps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(f"{_MODULE}.create_draft_skeleton", return_value="Todo created: my-slug") as mock_create:
            _handle_todo_create(["my-slug", "--after", "dep-a,dep-b"])

        mock_create.assert_called_once_with("/repo", "my-slug", after=["dep-a", "dep-b"], kind="feature")

    def test_passes_kind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(f"{_MODULE}.create_draft_skeleton", return_value="Todo created: my-slug") as mock_create:
            _handle_todo_create(["my-slug", "--kind", "migration"])

        mock_create.assert_called_once_with("/repo", "my-slug", after=None, kind="migration")

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_create([])


class TestHandleTodoDesign:
    """telec todo design [<slug>]."""

    def test_design_delegates_to_tool_command(self) -> None:
        with patch(f"{_MODULE}.handle_todo_design") as mock_design:
            _handle_todo_design(["my-slug"])

        mock_design.assert_called_once_with(["my-slug"])


class TestHandleTodoReconcile:
    """telec todo reconcile <slug> [--stage prepare|work]."""

    def test_success_prints_confirmation(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(
            f"{_MODULE}.reconcile_phase_state",
            return_value={"lifecycle_phase": "plan_review"},
        ) as mock_reconcile:
            _handle_todo_reconcile(["my-slug"])

        assert "Reconciled my-slug lifecycle_phase=plan_review" in capsys.readouterr().out
        mock_reconcile.assert_called_once_with("/repo", "my-slug", None)

    def test_passes_explicit_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(
            f"{_MODULE}.reconcile_phase_state",
            return_value={"lifecycle_phase": "build_complete"},
        ) as mock_reconcile:
            _handle_todo_reconcile(["my-slug", "--stage", "work"])

        mock_reconcile.assert_called_once_with("/repo", "my-slug", "work")

    def test_unknown_stage_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_reconcile(["my-slug", "--stage", "elsewhere"])


class TestHandleTodoRemove:
    """telec todo remove <slug>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        receipt = {"operation_id": "op-1", "kind": "todo_remove", "state": "queued", "poll_after_ms": 250}
        completed = {"operation_id": "op-1", "kind": "todo_remove", "state": "completed", "result": "removed my-slug"}

        with (
            patch(f"{_MODULE}.tool_api_call", return_value=receipt),
            patch(f"{_MODULE}.poll_operation", return_value=completed),
        ):
            _handle_todo_remove(["my-slug"])

        assert "Removed todo: my-slug" in capsys.readouterr().out

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_remove([])


class TestHandleTodoRename:
    """telec todo rename <old-slug> <new-slug>."""

    def test_success_prints_confirmation(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        snapshot: SnapshotAssertion,
    ) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        receipt = {"operation_id": "op-1", "kind": "todo_rename", "state": "queued", "poll_after_ms": 250}
        completed = {"operation_id": "op-1", "kind": "todo_rename", "state": "completed", "result": _RENAME_RESULT}

        with (
            patch(f"{_MODULE}.uuid.uuid4", return_value="req-1"),
            patch(f"{_MODULE}.tool_api_call", return_value=receipt) as api_call,
            patch(f"{_MODULE}.poll_operation", return_value=completed),
        ):
            _handle_todo_rename(["old-slug", "new-slug"])

        assert capsys.readouterr().out == snapshot
        api_call.assert_called_once_with(
            "POST",
            "/todos/rename",
            json_body={
                "old_slug": "old-slug",
                "new_slug": "new-slug",
                "cwd": "/repo",
                "client_request_id": "req-1",
            },
        )

    def test_missing_target_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_rename(["old-slug"])


class TestHandleTodoSplit:
    """telec todo split <slug> --into <child>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}):
            _handle_todo_split(["parent", "--into", "child-a", "--into", "child-b"])

        output = capsys.readouterr().out
        assert "child-a" in output
        assert "child-b" in output

    def test_missing_children_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_split(["parent"])


class TestHandleTodoStampPrepareV2:
    """telec todo stamp v2 prepare flags."""

    def test_prd_approved_posts_stamp(self) -> None:
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

    def test_skip_flag_posts_reason(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--architecture-skipped", "single file"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="architecture_skipped",
            value="single file",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_drift_reviewed_posts_json_payload(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--drift-reviewed", "prd", "cosmetic", "comments"])

        kwargs = mock_stamp.await_args.kwargs
        assert kwargs["stamp_type"] == "drift_reviewed"
        assert kwargs["value"] == '{"artifact": "prd", "verdict": "cosmetic", "reason": "comments"}'


class TestHandleTodoStampEnsureProducer:
    """Lazy event-producer setup is opt-in at the CLI boundary for finalize_ready only."""

    def test_finalize_ready_initializes_producer_before_applying_stamp(self) -> None:
        """ensure_event_producer must run before apply_todo_stamp and the stamp must still flow through."""
        order: list[str] = []

        def _record_ensure() -> None:
            order.append("ensure")

        async def _record_apply(**_: object) -> dict[str, str]:
            order.append("apply")
            return {"status": "ok"}

        with (
            patch(f"{_MODULE}.ensure_event_producer", side_effect=_record_ensure),
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(side_effect=_record_apply)) as mock_apply,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--finalize-ready"])

        assert order == ["ensure", "apply"]
        mock_apply.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="finalize_ready",
            value="",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_build_complete_does_not_initialize_producer(self) -> None:
        """Stamps that do not emit events must not pay the Redis-connect cost."""
        with (
            patch(f"{_MODULE}.ensure_event_producer") as mock_ensure,
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})),
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--build-complete"])

        mock_ensure.assert_not_called()

    def test_verdict_stamp_does_not_initialize_producer(self) -> None:
        """Verdict stamps mutate state only — no event emission, no producer needed."""
        with (
            patch(f"{_MODULE}.ensure_event_producer") as mock_ensure,
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})),
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--verdict", "approve", "--phase", "build"])

        mock_ensure.assert_not_called()

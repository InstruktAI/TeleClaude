"""Characterization tests for teleclaude.cli.tui.views.preparation_actions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin

_ARTIFACTS = ["architecture", "implementation-plan"]
_HTTP_POST = "POST"
_REMOVE_SLUG = "my-slug"
_REMOVE_ENDPOINT = "/todos/remove"
_REMOVE_OPERATION_ID = "op-remove-123"
_REPO_PATH = "/repo"
_VERSION_TOTAL = 12

# --- PreparationViewActionsMixin._next_command (static method) ---


@pytest.mark.unit
def test_next_command_appends_slug_when_provided() -> None:
    result = PreparationViewActionsMixin._next_command("next-build", "my-slug")
    assert result == "/next-build my-slug"


@pytest.mark.unit
def test_next_command_returns_base_only_when_no_slug() -> None:
    result = PreparationViewActionsMixin._next_command("next-build", None)
    assert result == "/next-build"


@pytest.mark.unit
def test_next_command_with_different_base_and_slug() -> None:
    result = PreparationViewActionsMixin._next_command("prepare", "feat-x")
    assert result == "/prepare feat-x"


class _DummyPreparationView(PreparationViewActionsMixin):
    def __init__(self, context: tuple[str, str, str | None] | None) -> None:
        self._context = context
        self.app = SimpleNamespace(notify=Mock(), _refresh_data=Mock(), push_screen=self._push_screen)
        self._todo_row = None
        self._slug_to_project_path = {_REMOVE_SLUG: _REPO_PATH}
        self.opened_modal: dict[str, str] | None = None
        self.pushed_screen: object | None = None
        self.pushed_callback: object | None = None

    def _resolve_cursor_context(self) -> tuple[str, str, str | None] | None:
        return self._context

    def _resolve_todo_for_cursor(self):
        return self._todo_row

    def _current_todo_row(self):
        return self._todo_row

    def _current_file_row(self):
        return None

    def _open_session_modal(self, **kwargs):
        self.opened_modal = kwargs

    def _push_screen(self, screen: object, callback: object | None = None) -> None:
        self.pushed_screen = screen
        self.pushed_callback = callback


@pytest.mark.unit
def test_action_reconcile_routes_through_daemon_and_refreshes() -> None:
    """Reconcile must POST through the daemon so the mutation hook fires —
    direct in-process calls bypass the cache invalidation and leave the TUI
    rendering the pre-reconcile row.
    """
    view = _DummyPreparationView(("local", "/repo", "my-slug"))

    with patch(
        "teleclaude.cli.tui.views.preparation_actions.tool_api_request",
        return_value={"slug": "my-slug", "lifecycle_phase": "plan_review"},
    ) as mock_request:
        view.action_reconcile()

    mock_request.assert_called_once_with(
        "POST",
        "/todos/reconcile/my-slug",
        json_body={"cwd": "/repo"},
        timeout=10.0,
    )
    view.app.notify.assert_called_once_with("Reconciled my-slug lifecycle_phase=plan_review")
    view.app._refresh_data.assert_called_once_with()


@pytest.mark.unit
def test_action_reconcile_surfaces_errors() -> None:
    view = _DummyPreparationView(("local", "/repo", "my-slug"))

    with patch(
        "teleclaude.cli.tui.views.preparation_actions.tool_api_request",
        return_value={"detail": "No valid prepare phase matches the current todo state"},
    ):
        view.action_reconcile()

    view.app.notify.assert_called_once_with(
        "No valid prepare phase matches the current todo state",
        severity="error",
    )
    view.app._refresh_data.assert_not_called()


@pytest.mark.unit
def test_action_start_work_opens_modal_for_prepared_todo() -> None:
    view = _DummyPreparationView(("local", "/repo", "my-slug"))
    view._todo_row = SimpleNamespace(
        todo=SimpleNamespace(
            files=["implementation-plan"],
            lifecycle_phase="prepared",
        )
    )

    view.action_start_work()

    assert view.opened_modal == {
        "computer": "local",
        "project_path": "/repo",
        "default_message": "/next-work my-slug",
        "title": "Start Work: my-slug",
    }
    view.app.notify.assert_not_called()


@pytest.mark.unit
def test_action_start_work_blocks_non_prepared_todo() -> None:
    view = _DummyPreparationView(("local", "/repo", "my-slug"))
    view._todo_row = SimpleNamespace(
        todo=SimpleNamespace(
            files=["implementation-plan"],
            lifecycle_phase="plan_review",
        )
    )

    view.action_start_work()

    assert view.app.notify.call_count == 1
    call_args, call_kwargs = view.app.notify.call_args
    assert call_kwargs.get("severity") == "warning"
    assert "plan_review" in call_args[0]
    assert view.opened_modal is None


@pytest.mark.unit
def test_action_start_work_allows_resume_during_build() -> None:
    """Phases at-or-beyond `prepared` allow start/resume — ordinal gate, not equality."""
    view = _DummyPreparationView(("local", "/repo", "my-slug"))
    view._todo_row = SimpleNamespace(
        todo=SimpleNamespace(
            files=["implementation-plan"],
            lifecycle_phase="build_started",
        )
    )

    view.action_start_work()

    assert view.opened_modal is not None
    view.app.notify.assert_not_called()


class _ArtifactRemovalView(PreparationViewActionsMixin):
    def __init__(self, file_row: object) -> None:
        self._file_row = file_row
        self._slug_to_project_path = {"my-slug": "/repo"}
        self.app = SimpleNamespace(
            notify=Mock(),
            _refresh_data=Mock(),
            push_screen=lambda _modal, cb: cb(True),
        )

    def _current_file_row(self) -> object:
        return self._file_row


@pytest.mark.unit
def test_action_remove_artifact_deletes_selected_non_input_artifact() -> None:
    view = _ArtifactRemovalView(SimpleNamespace(artifact_name="prd", slug="my-slug", project_path="/repo"))

    with (
        patch("teleclaude.cli.tui.views.preparation_actions.ConfirmModal"),
        patch(
            "teleclaude.cli.tui.views.preparation_actions.tool_api_request",
            return_value={"status": "ok"},
        ) as mock_request,
    ):
        view.action_remove_artifact()

    mock_request.assert_called_once_with(
        "DELETE",
        "/todos/artifacts/my-slug/prd",
        params={"cwd": "/repo"},
        timeout=10.0,
    )
    view.app._refresh_data.assert_called_once_with()


@pytest.mark.unit
def test_action_remove_artifact_blocks_input_artifact() -> None:
    view = _ArtifactRemovalView(SimpleNamespace(artifact_name="input", slug="my-slug", project_path="/repo"))

    with patch("teleclaude.cli.tui.views.preparation_actions.tool_api_request") as mock_request:
        view.action_remove_artifact()

    # Behavioral outcome: no API call, one warning notification (prose is the
    # renderer's concern, not pinned here).
    mock_request.assert_not_called()
    assert view.app.notify.call_count == 1
    assert view.app.notify.call_args.kwargs == {"severity": "warning"}


# Todo-row branch of action_remove_artifact: when _current_file_row() returns
# None (cursor on a todo row), the unified action falls through to the original
# todo-removal logic. These tests pin the confirm-modal count display and the
# POST flow on that fall-through path. They use _DummyPreparationView (which
# returns None from _current_file_row by default), so a single entry point
# (action_remove_artifact) exercises both branches across the test suite.


@pytest.mark.unit
def test_action_remove_artifact_todo_row_confirmation_message(
    snapshot: SnapshotAssertion,
) -> None:
    view = _DummyPreparationView(("local", "/repo", _REMOVE_SLUG))
    view._todo_row = SimpleNamespace(
        slug=_REMOVE_SLUG,
        todo=TodoItem(
            slug=_REMOVE_SLUG,
            status=TodoStatus.PENDING,
            description=None,
            has_requirements=True,
            has_impl_plan=True,
            files=list(_ARTIFACTS),
            version_total=_VERSION_TOTAL,
        ),
    )

    view.action_remove_artifact()

    assert view.pushed_screen is not None
    assert view.pushed_screen._message == snapshot


@pytest.mark.unit
def test_action_remove_artifact_todo_row_confirm_posts_daemon_remove_and_notifies_pending_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _DummyPreparationView(("local", _REPO_PATH, _REMOVE_SLUG))
    view._todo_row = SimpleNamespace(
        slug=_REMOVE_SLUG,
        todo=TodoItem(
            slug=_REMOVE_SLUG,
            status=TodoStatus.PENDING,
            description=None,
            has_requirements=True,
            has_impl_plan=True,
            files=list(_ARTIFACTS),
            version_total=_VERSION_TOTAL,
        ),
    )
    requests: list[tuple[str, str, object, float | None]] = []

    def _fake_tool_api_request(
        method: str,
        path: str,
        *,
        json_body: object = None,
        timeout: float | None = None,
    ) -> dict[str, str]:
        requests.append((method, path, json_body, timeout))
        return {"operation_id": _REMOVE_OPERATION_ID}

    monkeypatch.setattr(
        "teleclaude.cli.tui.views.preparation_actions.tool_api_request",
        _fake_tool_api_request,
    )

    view.action_remove_artifact()
    assert callable(view.pushed_callback)
    view.pushed_callback(True)

    assert requests == [
        (
            _HTTP_POST,
            _REMOVE_ENDPOINT,
            {"slug": _REMOVE_SLUG, "cwd": _REPO_PATH},
            10.0,
        )
    ]
    view.app.notify.assert_called_once_with(f"Removing {_REMOVE_SLUG}...")
    view.app._refresh_data.assert_not_called()

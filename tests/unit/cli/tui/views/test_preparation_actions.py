"""Characterization tests for teleclaude.cli.tui.views.preparation_actions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin
from teleclaude.cli.tui.widgets.modals import ContentInputModal

_ARTIFACTS = ["architecture", "implementation-plan"]
_HTTP_POST = "POST"
_REMOVE_SLUG = "my-slug"
_REMOVE_ENDPOINT = "/todos/remove"
_REMOVE_OPERATION_ID = "op-remove-123"
_REPO_PATH = "/repo"
_VERSION_TOTAL = 12
_SLUG = "my-todo"
_KIND_TODO = "todo"
_SUBSTANTIVE_CONTENT = "This is a description"
_DUMP_ENDPOINT = "/todos/dump"

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
        self._slug_to_project_path = {_REMOVE_SLUG: _REPO_PATH, _SLUG: _REPO_PATH}
        self._projects_with_todos = []
        self._trashed_projects = set()
        self._icebox_projects = set()
        self._delivered_projects = set()
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

    def _current_item(self):
        return None

    def _open_session_modal(self, **kwargs):
        self.opened_modal = kwargs

    def _push_screen(self, screen: object, callback: object | None = None) -> None:
        self.pushed_screen = screen
        self.pushed_callback = callback

    def post_message(self, message: object) -> None:
        pass

    def _rebuild(self) -> None:
        pass


@pytest.mark.unit
def test_action_reconcile_routes_through_daemon_and_refreshes() -> None:
    """Reconcile must POST through the daemon so the mutation hook fires."""
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
    assert call_args[0] == "Todo is not ready to start work: lifecycle_phase 'plan_review' is before 'prepared'"
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

    mock_request.assert_not_called()
    assert view.app.notify.call_count == 1
    assert view.app.notify.call_args.kwargs == {"severity": "warning"}


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
        **_kwargs: object,
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


@pytest.mark.unit
def test_create_item_opens_content_modal_before_post() -> None:
    view = _DummyPreparationView(("local", "/repo", _SLUG))
    with patch.object(view, "tool_api_request", create=True):
        view._create_item(_SLUG, kind=_KIND_TODO)
    assert isinstance(view.pushed_screen, ContentInputModal)


@pytest.mark.unit
def test_create_item_cancelled_modal_does_not_post(monkeypatch: pytest.MonkeyPatch) -> None:
    api_calls: list = []
    monkeypatch.setattr(
        "teleclaude.cli.tui.views.preparation_actions.tool_api_request",
        lambda *a, **_kw: api_calls.append(a),
    )
    view = _DummyPreparationView(("local", "/repo", _SLUG))
    view._create_item(_SLUG, kind=_KIND_TODO)
    if view.pushed_callback:
        view.pushed_callback(None)  # type: ignore[operator]
    assert not api_calls


@pytest.mark.unit
def test_create_item_substantive_content_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    api_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "teleclaude.cli.tui.views.preparation_actions.tool_api_request",
        lambda method, path, **_kw: api_calls.append((method, path)) or {"status": "ok"},
    )
    view = _DummyPreparationView(("local", "/repo", _SLUG))
    view._create_item(_SLUG, kind=_KIND_TODO)
    if view.pushed_callback:
        view.pushed_callback(_SUBSTANTIVE_CONTENT)  # type: ignore[operator]
    assert api_calls
    assert api_calls[0][1] == _DUMP_ENDPOINT


@pytest.mark.unit
def test_action_toggle_icebox_updates_view_state() -> None:
    """i: toggle_icebox must update _icebox_projects set."""
    view = _DummyPreparationView(("local", _REPO_PATH, None))
    project_path = "/path/to/project"

    with patch.object(view, "_resolve_cursor_context", return_value=("comp", project_path, None)):
        view.action_toggle_icebox()
        assert project_path in view._icebox_projects

        view.action_toggle_icebox()
        assert project_path not in view._icebox_projects


@pytest.mark.unit
def test_action_toggle_delivered_updates_view_state() -> None:
    """d: toggle_delivered must update _delivered_projects set."""
    view = _DummyPreparationView(("local", _REPO_PATH, None))
    project_path = "/path/to/project"

    with patch.object(view, "_resolve_cursor_context", return_value=("comp", project_path, None)):
        view.action_toggle_delivered()
        assert project_path in view._delivered_projects

        view.action_toggle_delivered()
        assert project_path not in view._delivered_projects


@pytest.mark.unit
def test_action_toggle_trashed_updates_view_state() -> None:
    """x: toggle_trashed must update _trashed_projects set."""
    view = _DummyPreparationView(("local", _REPO_PATH, None))
    project_path = "/path/to/project"

    with patch.object(view, "_resolve_cursor_context", return_value=("comp", project_path, None)):
        view.action_toggle_trashed()
        assert project_path in view._trashed_projects

        view.action_toggle_trashed()
        assert project_path not in view._trashed_projects


@pytest.mark.unit
def test_action_reactivate_selected_dispatches_request() -> None:
    """U: reactivate_selected must call the API for a removed todo."""
    view = _DummyPreparationView(("local", _REPO_PATH, "trashed"))
    roadmap_id = "row-123"
    todo = TodoItem(
        slug="trashed",
        status=TodoStatus.REMOVED,
        description="Test",
        has_requirements=True,
        has_impl_plan=False,
        roadmap_id=roadmap_id,
    )

    with (
        patch.object(view, "_current_todo_row", return_value=Mock(todo=todo, slug="trashed")),
        patch("teleclaude.cli.tui.views.preparation_actions.tool_api_request") as mock_request,
    ):
        view._slug_to_project_path = {"trashed": "/path/to/project"}
        mock_request.return_value = {"status": "ok"}

        view.action_reactivate_selected()

        mock_request.assert_called_once()
        args, _kwargs = mock_request.call_args
        assert args[0] == "POST"
        assert args[1] == f"/todos/by-id/{roadmap_id}/reactivate"

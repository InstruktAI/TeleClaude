"""Characterization tests for teleclaude.cli.tui.views.preparation_actions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin

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
        self.app = SimpleNamespace(notify=Mock(), _refresh_data=Mock())
        self._todo_row = None
        self.opened_modal: dict[str, str] | None = None

    def _resolve_cursor_context(self) -> tuple[str, str, str | None] | None:
        return self._context

    def _resolve_todo_for_cursor(self):
        return self._todo_row

    def _open_session_modal(self, **kwargs):
        self.opened_modal = kwargs


@pytest.mark.unit
def test_action_reconcile_calls_reconcile_and_refreshes() -> None:
    view = _DummyPreparationView(("local", "/repo", "my-slug"))

    with patch(
        "teleclaude.cli.tui.views.preparation_actions.reconcile_phase_state",
        return_value={"lifecycle_phase": "plan_review"},
    ) as mock_reconcile:
        view.action_reconcile()

    mock_reconcile.assert_called_once_with("/repo", "my-slug")
    view.app.notify.assert_called_once_with("Reconciled my-slug lifecycle_phase=plan_review")
    view.app._refresh_data.assert_called_once_with()


@pytest.mark.unit
def test_action_reconcile_surfaces_errors() -> None:
    view = _DummyPreparationView(("local", "/repo", "my-slug"))

    with patch(
        "teleclaude.cli.tui.views.preparation_actions.reconcile_phase_state",
        side_effect=ValueError("No valid prepare phase matches the current todo state"),
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

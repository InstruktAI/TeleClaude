"""Functional tests for TUI preparation actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

import teleclaude.cli.tui.state_store as state_store
from teleclaude.api_models import ComputerDTO, ProjectWithTodosDTO, TodoDTO
from teleclaude.cli.tui.messages import ChipFilterToggle, JumpToSession
from teleclaude.cli.tui.theme import get_selection_fg_hex
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views import preparation_actions
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import ContentInputModal, CreateSlugModal
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional

XNAV_SPEC = "project/spec/feature/tui/todo-session-cross-navigation"

ALICE = {"name": "Alice Smith", "email": "alice@example.com", "slug": "alice-smith"}
BOB = {"name": "Bob Jones", "email": "bob@example.com", "slug": "bob-jones"}


def _todo_dto(
    slug: str,
    *,
    created_by_principal: str | None = None,
    active_runner: str | None = None,
    schedule: str | None = None,
) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status="active",
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase="build_started",
        created_by_principal=created_by_principal,
        active_runner=active_runner,
        schedule=schedule,
    )


def _project_with(todos: list[TodoDTO]) -> ProjectWithTodosDTO:
    return ProjectWithTodosDTO(computer="local", name="proj", path="/proj", todos=todos)


class _PrepApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.jumped: list[str] = []
        self.filtered: list[str] = []

    def compose(self) -> ComposeResult:
        yield PreparationView(id="preparation-view")

    def on_jump_to_session(self, message: JumpToSession) -> None:
        self.jumped.append(message.session_id)

    def on_chip_filter_toggle(self, message: ChipFilterToggle) -> None:
        self.filtered.append(message.person_email)


def _todo_rows(view: PreparationView) -> list[TodoRow]:
    return [w for w in view._nav_items if isinstance(w, TodoRow)]


def _chip_span(row: TodoRow) -> object | None:
    rendered = row.render()
    region = row._chip_region
    if region is None:
        return None
    for span in rendered._spans:
        if span.start == region[0] and span.end == region[1]:
            return span
    return None


_DUMP_PATH = "/todos/dump"
_PREPARE_PATH = "/todos/prepare"
_WORK_PATH = "/todos/work"
_METHOD_POST = "POST"
_TODO_SLUG = "kindless-todo"
_BUG_SLUG = "broken-thing"
_CONTENT = "captured content\nwith multiple lines"
_KIND_BUG = "bug"
_SEVERITY_WARNING = "warning"


class _RecordingApp:
    def __init__(self) -> None:
        self.pushed: list[tuple[object, Callable[[str | None], None]]] = []
        self.notify = MagicMock()
        self._refresh_data = MagicMock()

    def push_screen(self, modal: object, callback: Callable[[str | None], None]) -> None:
        self.pushed.append((modal, callback))


class _Harness(PreparationViewActionsMixin):
    def __init__(self, project_root: Path) -> None:
        self.app = _RecordingApp()
        self._project_root = project_root
        self._slug_to_project_path = {"selected": str(project_root)}
        self._current: object | None = None

    def _current_item(self) -> object | None:
        return self._current

    def _current_todo_row(self) -> TodoRow | None:
        return self._current if isinstance(self._current, TodoRow) else None

    def _resolve_cursor_context(self) -> tuple[str, str, str | None] | None:
        return "local", str(self._project_root), "selected"

    def _resolve_todo_for_cursor(self) -> TodoRow | None:
        return self._current_todo_row()


def _drive_action(harness: _Harness, action: Callable[[], None], slug: str) -> None:
    action()
    slug_modal, slug_callback = harness.app.pushed.pop(0)
    assert isinstance(slug_modal, CreateSlugModal)

    slug_callback(slug)
    content_modal, content_callback = harness.app.pushed.pop(0)
    assert isinstance(content_modal, ContentInputModal)

    content_callback(_CONTENT)


def test_action_new_todo_dispatches_kindless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    _drive_action(harness, harness.action_new_todo, _TODO_SLUG)

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _DUMP_PATH)
    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["slug"] == _TODO_SLUG
    assert json_body["content"] == _CONTENT
    assert json_body["kind"] is None
    assert Path(json_body["cwd"]) == tmp_path


def test_action_new_bug_dispatches_bug_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    _drive_action(harness, harness.action_new_bug, _BUG_SLUG)

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _DUMP_PATH)
    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["slug"] == _BUG_SLUG
    assert json_body["content"] == _CONTENT
    assert json_body["kind"] == _KIND_BUG
    assert Path(json_body["cwd"]) == tmp_path


def _todo_row(
    *,
    hold: bool = False,
    held: bool = False,
    status: TodoStatus = TodoStatus.IN_PROGRESS,
    lifecycle_phase: str = "plan_drafting",
    active_runner: str | None = None,
    kind: str = "change",
    task_plan_digest: str | None = None,
    task_approved_digest: str | None = None,
) -> TodoRow:
    item = TodoItem(
        slug="selected",
        status=status,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind=kind,
        lifecycle_phase=lifecycle_phase,
        hold=hold,
        held=held,
        active_runner=active_runner,
        task_plan_digest=task_plan_digest,
        task_approved_digest=task_approved_digest,
    )
    return TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))


def test_hold_action_releases_when_held(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    # The offered control IS the unhold control: present exactly when the active
    # todo is held, and it clears the flag (release).
    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="build_started")
    assert harness.check_action("hold", ()) is True
    harness.action_hold()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/update")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "release": True,
    }

    # A todo that is not held offers no control.
    harness._current = _todo_row(hold=False, held=False, lifecycle_phase="build_started")
    assert harness.check_action("hold", ()) is False

    harness._current = _todo_row(hold=True, held=True, status=TodoStatus.ICEBOX)
    assert harness.check_action("hold", ()) is False


def test_hold_control_available_for_held_prepare_todo(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="prepared")
    assert harness.check_action("hold", ()) is True


def test_release_action_does_not_exist(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    assert not hasattr(harness, "action_release")
    assert not hasattr(harness, "action_release_hold")


def test_approve_and_hold_are_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    # The approval gate is observed independently of the hold flag.
    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="prd_human_approval")
    assert harness.check_action("approve_gate", ()) is True

    # The unhold control is exposed for a held todo regardless of any approval
    # state, and an approval gate does not suppress it.
    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="prd_human_approval")
    assert harness.check_action("hold", ()) is True

    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="prd_human_approval")
    harness.action_approve_gate()
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/stamp")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "stamp_type": "prd_approved",
        "notify_runner": True,
    }


def test_no_human_gate_controls_for_running_or_work_ready_todos(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    # Prepared and unheld: no approval pending, no unhold control.
    harness._current = _todo_row(lifecycle_phase="prepared", hold=False, held=False)
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("hold", ()) is False

    harness._current = _todo_row(active_runner="runner-session", lifecycle_phase="plan_drafting")
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("hold", ()) is False


def test_task_authorization_uses_task_approved_stamp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row(
        kind="task",
        lifecycle_phase="prepared",
        task_plan_digest="plan-digest",
        task_approved_digest=None,
    )

    assert harness.check_action("approve_gate", ()) is True
    harness.action_approve_gate()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/stamp")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "stamp_type": "task_approved",
        "notify_runner": True,
    }


def test_task_authorization_action_suppressed_when_digest_current(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    harness._current = _todo_row(
        kind="task",
        lifecycle_phase="prepared",
        task_plan_digest="plan-digest",
        task_approved_digest="plan-digest",
    )

    assert harness.check_action("approve_gate", ()) is False


def test_computer_header_action_gating(tmp_path: Path) -> None:
    computer = ComputerDTO(name="test-comp", status="active", is_local=True)
    header = ComputerHeader(ComputerDisplayInfo(computer=computer, session_count=0, recent_activity=False))
    harness = _Harness(tmp_path)
    harness._current = header

    assert harness.check_action("toggle_delivered", ()) is False
    assert harness.check_action("toggle_icebox", ()) is False
    assert harness.check_action("toggle_trashed", ()) is False
    assert harness.check_action("new_project", ()) is True


def test_action_prepare_posts_operation_instead_of_opening_session_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool_api_request = MagicMock(return_value={"operation_id": "op-prepare"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row()

    harness.action_prepare()

    assert harness.app.pushed == []
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _PREPARE_PATH)
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
    }
    harness.app._refresh_data.assert_called_once()


def test_action_start_work_posts_operation_after_readiness_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool_api_request = MagicMock(return_value={"operation_id": "op-work"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row(lifecycle_phase="prepared")

    harness.action_start_work()

    assert harness.app.pushed == []
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _WORK_PATH)
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
    }
    harness.app._refresh_data.assert_called_once()


def test_action_start_work_submits_task_without_sdlc_readiness_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool_api_request = MagicMock(return_value={"operation_id": "op-task-run"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    # is_ready_for_work rejects every task; the TUI must not pre-gate a task —
    # it submits and lets the server resolve the task-run lane.
    harness._current = _todo_row(
        kind="task",
        lifecycle_phase="prepared",
        task_plan_digest="plan-a",
        task_approved_digest="plan-a",
    )

    harness.action_start_work()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _WORK_PATH)
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
    }
    warning_calls = [
        call for call in harness.app.notify.call_args_list if call.kwargs.get("severity") == _SEVERITY_WARNING
    ]
    assert warning_calls == []


def test_action_start_work_still_gates_unready_sdlc_todo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"operation_id": "op-work"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row(kind="change", lifecycle_phase="plan_drafting")

    harness.action_start_work()

    tool_api_request.assert_not_called()
    assert harness.app.notify.call_args.kwargs.get("severity") == _SEVERITY_WARNING


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-9")
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-10")
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-11")
async def test_claim_columns_jump_projection_and_select(wire_people, snapshot) -> None:
    # Consolidated into one App.run_test session to keep the scoped-suite
    # wall-clock budget: the DTO->TodoItem projection (chip render), select_todo
    # landing, and the claim-column jump regime (UC-9/10/11) all exercised here.
    runner = "runner-xyz"
    wire_people([ALICE, BOB])
    app = _PrepApp()
    async with app.run_test(size=(120, 20)) as pilot:
        view = app.query_one(PreparationView)
        view.update_data(
            [
                _project_with(
                    [
                        _todo_dto(
                            "claimed",
                            created_by_principal="human:alice@example.com",
                            active_runner=runner,
                            schedule="cron:* * * * *",
                        ),
                        _todo_dto("unclaimed", active_runner=None),
                    ]
                )
            ]
        )
        await pilot.pause()
        rows = {r.slug: r for r in _todo_rows(view)}
        claimed, unclaimed = rows["claimed"], rows["unclaimed"]
        unclaimed.render()

        # Projection: created_by_principal flows DTO->TodoItem end to end, so the
        # claimed row renders alice's author chip (pinned by the snapshot).
        assert claimed.render().plain == snapshot

        # select_todo lands the cursor on the matching row.
        assert view.select_todo("unclaimed") is True

        # UC-9: the claimed text column jumps to the runner session.
        assert claimed._claim_region is not None
        await pilot.click(claimed, offset=(1 + claimed._claim_region[0], 0))
        await pilot.pause()
        assert app.jumped == [runner]

        # UC-10: the unclaimed row records no claim region; a column click selects.
        assert unclaimed._claim_region is None
        await pilot.click(unclaimed, offset=(20, 0))
        await pilot.pause()
        assert app.jumped == [runner]

        # UC-11: the state-icon column sits past the claim region; clicking it does
        # not jump (icons excluded from the claim regime).
        await pilot.click(claimed, offset=(1 + claimed._claim_region[1] + 1, 0))
        await pilot.pause()
        assert app.jumped == [runner]


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-14")
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-15")
async def test_shared_human_filter_flows(wire_people) -> None:
    # One session covers the chip-click toggle, the set-filter hide+invert
    # (UC-14), and the clear-filter restore (UC-15).
    alice_email = "alice@example.com"
    wire_people([ALICE, BOB])
    app = _PrepApp()
    async with app.run_test(size=(120, 20)) as pilot:
        view = app.query_one(PreparationView)
        view.update_data(
            [
                _project_with(
                    [
                        _todo_dto("alice-work", created_by_principal=f"human:{alice_email}"),
                        _todo_dto("bob-work", created_by_principal="human:bob@example.com"),
                    ]
                )
            ]
        )
        await pilot.pause()
        rows = {r.slug: r for r in _todo_rows(view)}
        alice_row, bob_row = rows["alice-work"], rows["bob-work"]
        normal = _chip_span(alice_row)

        # Clicking the owner chip posts the shared-filter toggle for that person.
        alice_row.render()
        assert alice_row._chip_region is not None
        await pilot.click(alice_row, offset=(1 + alice_row._chip_region[0], 0))
        await pilot.pause()
        assert app.filtered == [alice_email]

        # UC-14: applying the filter hides the non-matching row and pushes the
        # filtered person's chip to the selection extreme (pole text, not its
        # resting low-contrast colors).
        view.set_human_filter(alice_email)
        await pilot.pause()
        assert alice_row.display is True
        assert bob_row.display is False
        inverted = _chip_span(alice_row)
        assert normal is not None and inverted is not None
        assert inverted.style.color.name == get_selection_fg_hex()
        assert inverted.style.color != normal.style.color

        # UC-15: clearing restores every row and renders chips at rest again.
        view.set_human_filter(None)
        await pilot.pause()
        assert bob_row.display is True
        restored = _chip_span(alice_row)
        assert restored is not None
        assert restored.style.color == normal.style.color
        assert restored.style.bgcolor == normal.style.bgcolor


def test_human_filter_persists_across_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # State-store round-trip mechanism. UC-XNAV-16 is bound by the full-app
    # filter-persistence integration test in test_todo_session_cross_navigation.
    email = "alice@example.com"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")

    # The app persists the one shared filter in the `app` namespace.
    state_store.save_state({"app": {"active_tab": "preparation", "human_filter": email}})

    # A fresh process (load_state) sees the same filter — one source of truth.
    reloaded = state_store.load_state()
    assert reloaded["app"]["human_filter"] == email


@pytest.mark.asyncio
async def test_single_user_surface_suppressed_but_jumps_active(wire_people) -> None:
    # SC-6: single-user suppresses the chip and makes the filter inert, while the
    # claim-state jump stays active.
    runner = "runner-solo"
    wire_people([ALICE])
    app = _PrepApp()
    async with app.run_test(size=(120, 20)) as pilot:
        view = app.query_one(PreparationView)
        view.update_data(
            [
                _project_with(
                    [_todo_dto("claimed", created_by_principal="human:alice@example.com", active_runner=runner)]
                )
            ]
        )
        await pilot.pause()
        row = _todo_rows(view)[0]
        row.render()
        # No chip in single-user, but the claim region (jump target) is present.
        assert row._chip_region is None
        assert row._claim_region is not None
        await pilot.click(row, offset=(1 + row._claim_region[0], 0))
        await pilot.pause()
        assert app.jumped == [runner]

        # The filter is inert: a stale value hides nothing.
        view.set_human_filter("nobody@example.com")
        await pilot.pause()
        assert row.display is True

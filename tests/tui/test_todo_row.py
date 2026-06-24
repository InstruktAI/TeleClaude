"""Functional tests for todo row rendering."""

from __future__ import annotations

import pytest

import teleclaude.cli.tui.widgets.chip as chip_mod
import teleclaude.cli.tui.widgets.todo_row as todo_row_mod
from teleclaude.cli.tui import theme
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.core.next_machine.lifecycle import LifecyclePhase

pytestmark = pytest.mark.functional

XNAV_SPEC = "project/spec/feature/tui/todo-session-cross-navigation"

ALICE = {"name": "Alice Smith", "email": "alice@example.com", "slug": "alice-smith"}
BOB = {"name": "Bob Jones", "email": "bob@example.com", "slug": "bob-jones"}


def _owned_todo(principal: str | None) -> TodoItem:
    return TodoItem(
        slug="owned-work",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase=None,
        created_by_principal=principal,
    )


def _row(item: TodoItem) -> TodoRow:
    return TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))


def _span_over(rendered: object, text: str) -> object | None:
    pos = rendered.plain.index(text)
    for span in rendered._spans:
        if span.start == pos and span.end == pos + len(text):
            return span
    return None


def test_kindless_todo_row_renders_question_mark_kind_and_classify_phase(snapshot: object) -> None:
    item = TodoItem(
        slug="classify-me",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind=None,
        lifecycle_phase=None,
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_renders_compact_kind_labels(snapshot: object) -> None:
    items = [
        TodoItem(
            slug="my-feature",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="feature",
            lifecycle_phase=None,
        ),
        TodoItem(
            slug="my-change",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="change",
            lifecycle_phase=None,
        ),
        TodoItem(
            slug="my-bug",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="bug",
            lifecycle_phase=None,
        ),
        TodoItem(
            slug="my-task",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="task",
            lifecycle_phase=None,
        ),
    ]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    rows = [TodoRow(item, slug_width=slug_width, col_widths=col_widths) for item in items]

    assert [r.render().plain for r in rows] == snapshot


def test_todo_row_renders_disapproved_review_status(snapshot: object) -> None:
    item = TodoItem(
        slug="fix-review",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="change",
        lifecycle_phase="review_changes_requested",
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_renders_hold_distinct_from_icebox(snapshot: object) -> None:
    items = [
        TodoItem(
            slug="held-work",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="change",
            lifecycle_phase="build_started",
            hold=True,
            held=True,
            hold_source="manual",
        ),
        TodoItem(
            slug="frozen-work",
            status=TodoStatus.ICEBOX,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="change",
            lifecycle_phase="plan_drafting",
        ),
    ]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    rows = [TodoRow(item, slug_width=slug_width, col_widths=col_widths) for item in items]

    assert [row.render().plain for row in rows] == snapshot


def test_todo_row_renders_pending_approval_distinct_from_hold(snapshot: object) -> None:
    items = [
        TodoItem(
            slug="approval-work",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="feature",
            lifecycle_phase="prd_human_approval",
            hold=True,
            held=False,
        ),
        TodoItem(
            slug="held-work",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="feature",
            lifecycle_phase="build_started",
            hold=True,
            held=True,
        ),
    ]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    rows = [TodoRow(item, slug_width=slug_width, col_widths=col_widths) for item in items]

    assert [row.render().plain for row in rows] == snapshot


def test_todo_row_renders_task_authorization_and_schedule_state(snapshot: object) -> None:
    items = [
        TodoItem(
            slug="task-pending",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="task",
            lifecycle_phase="prepared",
            task_plan_digest="digest-a",
        ),
        TodoItem(
            slug="task-authorized",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="task",
            lifecycle_phase="prepared",
            task_plan_digest="digest-b",
            task_approved_digest="digest-b",
        ),
        TodoItem(
            slug="task-stale",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="task",
            lifecycle_phase="prepared",
            schedule="cron:* * * * *",
            task_plan_digest="digest-c",
            task_approved_digest="old-digest",
        ),
    ]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    rows = [TodoRow(item, slug_width=slug_width, col_widths=col_widths) for item in items]

    assert [row.render().plain for row in rows] == snapshot


def test_todo_row_suppresses_hold_glyph_when_not_effectively_held(snapshot: object) -> None:
    # A residual ``hold`` flag whose derived verdict is not effectively held
    # (autostart off, runner manual, or still in the prepare lane) renders no
    # lock glyph: the widget reads only the pre-derived ``held`` verdict.
    item = TodoItem(
        slug="legacy-held",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="change",
        lifecycle_phase="prepared",
        hold=True,
        held=False,
        hold_source="manual",
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_kind_column_color_per_kind_in_dark_and_light_mode(
    monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    """Kind column applies distinct per-kind colors in dark and light mode."""
    kinds: list[str | None] = ["feature", "change", "bug", "task", None]
    results: list[tuple[str, str, str | None]] = []

    slug_names = ["alpha", "bravo", "charlie", "delta", "echo"]
    for kind, slug in zip(kinds, slug_names):
        item = TodoItem(
            slug=slug,
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind=kind,
            lifecycle_phase=None,
        )
        row = TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))
        kind_display = todo_row_mod._display_kind(kind)

        for mode, is_dark in [("dark", True), ("light", False)]:
            monkeypatch.setattr(todo_row_mod, "is_dark_mode", lambda _d=is_dark: _d)
            rendered = row.render()
            kind_pos = rendered.plain.index(kind_display)
            kind_color: str | None = None
            for span in rendered._spans:
                if span.start == kind_pos and span.end == kind_pos + len(kind_display):
                    if hasattr(span.style, "color") and span.style.color:
                        kind_color = span.style.color.name
                        break
            results.append((kind or "kindless", mode, kind_color))

    assert results == snapshot


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-2")
def test_todo_author_chip_resolves_initials_and_colors(wire_people, monkeypatch, snapshot) -> None:
    background, text = "#112233", "#ddeeff"
    wire_people(
        [ALICE, BOB],
        overlays={"alice-smith": f"color:\n  background:\n    dark: '{background}'\n  text:\n    dark: '{text}'\n"},
    )
    monkeypatch.setattr(chip_mod, "is_dark_mode", lambda: True)

    rendered = _row(_owned_todo("human:alice@example.com")).render()

    span = _span_over(rendered, "AS")
    assert span is not None
    # Colors resolve from alice's PersonConfig.color overlay.
    assert span.style.bgcolor.name == background
    assert span.style.color.name == text
    assert rendered.plain == snapshot


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-8")
def test_todo_author_chip_carries_no_padding(wire_people, monkeypatch) -> None:
    wire_people([ALICE, BOB])
    monkeypatch.setattr(chip_mod, "is_dark_mode", lambda: True)

    rendered = _row(_owned_todo("human:alice@example.com")).render()

    span = _span_over(rendered, "AS")
    # The styled region spans exactly the initials (enforced by _span_over's
    # exact-boundary match); the separating space after it sits outside the
    # styled region in the base style.
    assert span is not None
    assert rendered.plain[span.end].isspace()


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-1")
def test_todo_chip_color_theme_default_and_verbatim(wire_people, monkeypatch) -> None:
    text_dark = "#445566"
    # alice sets only text.dark; bob sets nothing.
    wire_people([ALICE, BOB], overlays={"alice-smith": f"color:\n  text:\n    dark: '{text_dark}'\n"})
    monkeypatch.setattr(chip_mod, "is_dark_mode", lambda: True)

    alice_span = _span_over(_row(_owned_todo("human:alice@example.com")).render(), "AS")
    bob_span = _span_over(_row(_owned_todo("human:bob@example.com")).render(), "BJ")

    assert alice_span is not None and bob_span is not None
    # Unset background.dark → theme neutral subtle-grey default; set text.dark → verbatim.
    assert alice_span.style.bgcolor.name == theme.get_neutral_color("subtle")
    assert alice_span.style.color.name == text_dark
    # Fully unset → both cells fall back to the theme neutral defaults.
    assert bob_span.style.bgcolor.name == theme.get_neutral_color("subtle")
    assert bob_span.style.color.name == theme.get_neutral_color("highlight")


def _kind_todo(*, claimed: bool) -> TodoItem:
    return TodoItem(
        slug="claim-work",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase=None,
        active_runner="runner-1" if claimed else None,
    )


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-10")
def test_todo_text_columns_bold_only_when_claimed() -> None:
    # The text status columns carry bold weight only while the todo is claimed by
    # a live runner; an unclaimed todo renders them at normal weight. Asserting on
    # the span's bold flag (not .plain) is what guards the claim-state signal.
    claimed = _span_over(_row(_kind_todo(claimed=True)).render(), "feat")
    unclaimed = _span_over(_row(_kind_todo(claimed=False)).render(), "feat")
    assert claimed is not None and unclaimed is not None
    assert claimed.style.bold is True
    assert not unclaimed.style.bold


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-17")
def test_todo_chip_inversion_compounds_filter_and_selection(wire_people) -> None:
    # Selection and the live filter each invert the chip (background and text
    # swap); both at once cancel back to the resting colors.
    wire_people([ALICE, BOB])

    def chip(*, selected: bool, filtered: bool) -> object | None:
        row = _row(_owned_todo("human:alice@example.com"))
        if selected:
            row.add_class("selected")
        if filtered:
            row._active_human_filter = "alice@example.com"
        return _span_over(row.render(), "AS")

    resting = chip(selected=False, filtered=False)
    assert resting is not None
    for inverted in (chip(selected=True, filtered=False), chip(selected=False, filtered=True)):
        assert inverted is not None
        assert inverted.style.bgcolor.name == resting.style.color.name
        assert inverted.style.color.name == resting.style.bgcolor.name
    both = chip(selected=True, filtered=True)
    assert both is not None
    assert both.style.bgcolor.name == resting.style.bgcolor.name
    assert both.style.color.name == resting.style.color.name


def _status_item(
    status: TodoStatus,
    *,
    kind: str | None = "feature",
    lifecycle_phase: str | None = None,
    task_plan_digest: str | None = None,
    task_approved_digest: str | None = None,
    schedule: str | None = None,
) -> TodoItem:
    return TodoItem(
        slug="work",
        status=status,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind=kind,
        lifecycle_phase=lifecycle_phase,
        task_plan_digest=task_plan_digest,
        task_approved_digest=task_approved_digest,
        schedule=schedule,
    )


def test_todo_status_glyph_weight_and_color_track_status() -> None:
    # The active status glyph carries the active color + bold weight; a draft
    # glyph is the neutral draft color and not bold. `.plain` observes neither.
    # Kills: dropping `bold = label == active` in _status_style, or mapping the
    # active status to the draft color.
    colors = todo_row_mod._STATUS_COLORS_DARK if theme.is_dark_mode() else todo_row_mod._STATUS_COLORS_LIGHT
    active = _span_over(_row(_status_item(TodoStatus.IN_PROGRESS)).render(), "■")
    draft = _span_over(_row(_status_item(TodoStatus.PENDING)).render(), "□")
    assert active is not None and draft is not None
    assert active.style.bold is True
    assert not draft.style.bold
    assert active.style.color.name == colors["active"]
    assert draft.style.color.name == colors["draft"]


def test_todo_phase_column_color_marks_settled_vs_in_flight() -> None:
    # A settled-ok lifecycle phase renders its P-column value in the ok color; an
    # in-flight phase renders gold. `.plain` cannot see the distinction.
    # Kills: returning gold for a settled phase (or ok for an in-flight one) in
    # lifecycle_phase_label.
    settled = _row(_status_item(TodoStatus.IN_PROGRESS, lifecycle_phase=LifecyclePhase.PREPARED.value)).render()
    in_flight = _row(_status_item(TodoStatus.IN_PROGRESS, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value)).render()
    settled_span = _span_over(settled, "prepared")
    in_flight_span = _span_over(in_flight, "plan draft")
    assert settled_span is not None and in_flight_span is not None
    assert settled_span.style.color.name == todo_row_mod._ok_color()
    assert in_flight_span.style.color.name == todo_row_mod._gold_color()
    assert settled_span.style.color.name != in_flight_span.style.color.name


def test_todo_state_icons_carry_weight_and_semantic_color() -> None:
    # The task-authorized 'A' renders ok + bold; the authorization-pending '!'
    # renders gold + bold. `.plain` sees the glyph but neither its weight nor its
    # color. Kills: dropping bold on the icons, or swapping the ok/gold mapping.
    authorized = _row(
        _status_item(TodoStatus.IN_PROGRESS, kind="task", task_plan_digest="d", task_approved_digest="d")
    ).render()
    pending = _row(
        _status_item(
            TodoStatus.IN_PROGRESS,
            kind="task",
            lifecycle_phase="prepared",
            task_plan_digest="d",
            task_approved_digest="x",
        )
    ).render()
    a_icon = _span_over(authorized, "A")
    bang = _span_over(pending, "!")
    assert a_icon is not None and bang is not None
    assert a_icon.style.bold is True
    assert a_icon.style.color.name == todo_row_mod._ok_color()
    assert bang.style.bold is True
    assert bang.style.color.name == todo_row_mod._gold_color()


def test_single_user_suppresses_todo_chip(wire_people) -> None:
    # A sole registered person → single-user mode: the ownership surface is
    # suppressed, so an owned todo renders no chip (SC-6).
    wire_people([ALICE])
    row = _row(_owned_todo("human:alice@example.com"))
    row.render()
    assert row._chip_region is None


def test_multi_user_renders_todo_chip(wire_people) -> None:
    # The same todo in multi-user mode renders the chip (SC-6 contrast).
    wire_people([ALICE, BOB])
    row = _row(_owned_todo("human:alice@example.com"))
    row.render()
    assert row._chip_region is not None


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-4")
def test_todo_unresolvable_human_renders_no_chip(wire_people, snapshot) -> None:
    wire_people([ALICE, BOB])

    null_plain = _row(_owned_todo(None)).render().plain
    unknown_plain = _row(_owned_todo("human:nobody@example.com")).render().plain

    # Both unresolvable cases render identically — no chip, the gap closed (the
    # slug starts right after the status glyph, no reserved chip width).
    assert null_plain == unknown_plain
    assert null_plain == snapshot

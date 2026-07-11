"""Functional tests for todo row rendering."""

from __future__ import annotations

import pytest

import teleclaude.cli.tui.widgets.chip as chip_mod
import teleclaude.cli.tui.widgets.todo_row as todo_row_mod
from teleclaude.cli.tui import theme
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.utils.formatters import format_relative_time
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
        lineage=principal,
        human_involved=True,
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


def test_todo_row_renders_blocked_with_review_remediation_verdict(snapshot: object) -> None:
    item = TodoItem(
        slug="blocked-review",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=True,
        kind="change",
        lifecycle_phase=LifecyclePhase.BLOCKED.value,
        prepare_review_verdict="changes_requested",
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_renders_blocked_without_review_verdict(snapshot: object) -> None:
    item = TodoItem(
        slug="blocked-upstream",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=True,
        kind="feature",
        lifecycle_phase=LifecyclePhase.BLOCKED.value,
        prepare_review_verdict=None,
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_aligns_blocked_review_column_with_work_lane() -> None:
    """The BLOCKED-with-verdict `R` column shares one width slot (`sized["R"]`)
    with the work lane's `R` column; both rows must pad to the same total
    width so their trailing state columns land at the same offset."""
    items = [
        TodoItem(
            slug="blocked-review",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=True,
            kind="change",
            lifecycle_phase=LifecyclePhase.BLOCKED.value,
            prepare_review_verdict="changes_requested",
        ),
        TodoItem(
            slug="fix-review",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="change",
            lifecycle_phase="review_changes_requested",
        ),
    ]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    rows = [TodoRow(item, slug_width=slug_width, col_widths=col_widths) for item in items]

    rendered = [row.render().plain for row in rows]
    assert len(rendered[0]) == len(rendered[1])


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


def test_todo_row_renders_generic_approval_and_schedule_state(snapshot: object) -> None:
    # Task authorization surfaces through the generic P:approve phase column (no
    # dedicated per-task badge); the schedule badge renders in the state column.
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


def test_todo_row_renders_hold_glyph_for_held_prepare_todo(snapshot: object) -> None:
    item = TodoItem(
        slug="legacy-held",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="change",
        lifecycle_phase="prepared",
        hold=True,
        held=True,
        hold_source="manual",
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_renders_delivered_age_from_delivered_at() -> None:
    item = TodoItem(
        slug="shipped-work",
        status=TodoStatus.DELIVERED,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase=None,
        integration_phase="delivered",
        delivered_at="2026-06-01T12:00:00+00:00",
    )
    expected_age = format_relative_time(item.delivered_at)
    rendered = _row(item).render().plain
    assert f"I:{expected_age}" in rendered
    assert "I:delivered" not in rendered


def test_todo_row_renders_delivered_row_without_delivered_at() -> None:
    item = TodoItem(
        slug="shipped-work",
        status=TodoStatus.DELIVERED,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase=None,
        integration_phase="delivered",
        delivered_at=None,
    )
    rendered = _row(item).render().plain
    assert "I:delivered" not in rendered
    assert "I:" not in rendered


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

    # _span_over returns a span only when its boundaries exactly cover the
    # initials occurrence — so a non-None result proves the styled region is the
    # initials alone, with no padding bleeding into the chip style (the column's
    # muted-leader separation sits outside it).
    span = _span_over(rendered, "AS")
    assert span is not None


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
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-18")
def test_todo_chip_weight_and_color_track_selection_and_filter(wire_people) -> None:
    # Weight encodes selection alone; color encodes the rest. Resting: normal
    # weight, subtle bg / highlight text. Filter-on (not selected): colors swap,
    # still normal weight. Selected: bold, snapped to the high-contrast pole, and
    # selection dominates the filter.
    wire_people([ALICE, BOB])

    def chip(*, selected: bool, filtered: bool) -> object | None:
        row = _row(_owned_todo("human:alice@example.com"))
        if selected:
            row.add_class("selected")
        if filtered:
            row._active_human_filter = "alice@example.com"
        return _span_over(row.render(), "AS")

    resting = chip(selected=False, filtered=False)
    filtered = chip(selected=False, filtered=True)
    selected = chip(selected=True, filtered=False)
    both = chip(selected=True, filtered=True)
    assert all(s is not None for s in (resting, filtered, selected, both))
    pole = theme.get_selection_fg_hex()
    # Weight: bold only when selected.
    assert not resting.style.bold
    assert not filtered.style.bold
    assert selected.style.bold is True
    assert both.style.bold is True
    # Resting is low-contrast (not the pole). Filter-on and selection both take
    # the selection text pole over the opposite-pole fill (neutral chip).
    assert resting.style.color.name != pole
    for active in (filtered, selected, both):
        assert active.style.color.name == pole
        assert active.style.bgcolor.name in {"#000000", "#ffffff"}
        assert active.style.bgcolor.name != pole


def _status_item(
    status: TodoStatus,
    *,
    kind: str | None = "feature",
    lifecycle_phase: str | None = None,
    task_plan_digest: str | None = None,
    task_approved_digest: str | None = None,
    schedule: str | None = None,
    held: bool = False,
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
        held=held,
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


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-11")
def test_todo_state_column_badges_carry_weight_and_color() -> None:
    # The schedule 'S' badge and the hold glyph each render gold + bold in their
    # state-column slots. `.plain` sees the glyphs but neither weight nor color.
    # Kills: dropping the bold or the gold color on either badge.
    scheduled = _row(_status_item(TodoStatus.IN_PROGRESS, schedule="cron:* * * * *")).render()
    s_badge = _span_over(scheduled, "S")
    assert s_badge is not None
    assert s_badge.style.bold is True
    assert s_badge.style.color.name == todo_row_mod._gold_color()
    held = _row(_status_item(TodoStatus.IN_PROGRESS, held=True)).render()
    hold_glyph = _span_over(held, todo_row_mod._HOLD_ICON)
    assert hold_glyph is not None
    assert hold_glyph.style.bold is True
    assert hold_glyph.style.color.name == todo_row_mod._gold_color()


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

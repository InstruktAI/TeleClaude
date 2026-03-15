"""Characterization tests for teleclaude.cli.tui.views.base."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.views.base import BaseView, ScrollableViewMixin


class _ConcreteScrollable(ScrollableViewMixin[str]):
    """Minimal concrete class to exercise the scroll mixin."""

    def __init__(self, items: list[str]) -> None:
        self.flat_items = items
        self.selected_index = 0
        self.scroll_offset = 0
        self._last_rendered_range = (0, len(items) - 1) if items else (0, 0)


# --- BaseView ---


@pytest.mark.unit
def test_base_view_get_render_lines_raises_not_implemented() -> None:
    view = BaseView()
    with pytest.raises(NotImplementedError):
        view.get_render_lines(80, 24)


@pytest.mark.unit
def test_base_view_error_message_includes_class_name() -> None:
    class MyView(BaseView):
        pass

    view = MyView()
    with pytest.raises(NotImplementedError, match="MyView"):
        view.get_render_lines(80, 24)


# --- ScrollableViewMixin.move_up ---


@pytest.mark.unit
def test_move_up_decrements_selected_index() -> None:
    view = _ConcreteScrollable(["a", "b", "c"])
    view.selected_index = 2
    view.move_up()
    assert view.selected_index == 1


@pytest.mark.unit
def test_move_up_does_not_go_below_zero() -> None:
    view = _ConcreteScrollable(["a", "b"])
    view.selected_index = 0
    view.move_up()
    assert view.selected_index == 0


@pytest.mark.unit
def test_move_up_adjusts_scroll_offset_when_above_visible_area() -> None:
    view = _ConcreteScrollable(["a", "b", "c"])
    view.selected_index = 1
    view.scroll_offset = 1
    view.move_up()
    assert view.scroll_offset == view.selected_index


# --- ScrollableViewMixin.move_down ---


@pytest.mark.unit
def test_move_down_increments_selected_index() -> None:
    view = _ConcreteScrollable(["a", "b", "c"])
    view.selected_index = 0
    view.move_down()
    assert view.selected_index == 1


@pytest.mark.unit
def test_move_down_does_not_exceed_last_item() -> None:
    view = _ConcreteScrollable(["a", "b"])
    view.selected_index = 1
    view.move_down()
    assert view.selected_index == 1


@pytest.mark.unit
def test_move_down_does_nothing_when_items_empty() -> None:
    view = _ConcreteScrollable([])
    view.selected_index = 0
    view.move_down()
    assert view.selected_index == 0


@pytest.mark.unit
def test_move_down_adjusts_scroll_offset_when_beyond_rendered_range() -> None:
    view = _ConcreteScrollable(["a", "b", "c", "d", "e"])
    view.selected_index = 2
    view._last_rendered_range = (0, 2)
    view.move_down()
    # selected_index becomes 3, which is beyond last_rendered=2, so scroll_offset bumps by 1
    assert view.scroll_offset == 1

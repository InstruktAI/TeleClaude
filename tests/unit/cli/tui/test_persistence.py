from __future__ import annotations

import pytest

from teleclaude.cli.tui.persistence import get_persistence_key


class _WidgetWithId:
    def __init__(self, widget_id: str) -> None:
        self.id = widget_id


class _WidgetWithCustomKey:
    def __init__(self, widget_id: str, persistence_key: str) -> None:
        self.id = widget_id
        self.persistence_key = persistence_key


class _WidgetWithoutId:
    id = None


@pytest.mark.unit
def test_get_persistence_key_prefers_explicit_keys_and_normalizes_ids() -> None:
    assert get_persistence_key(_WidgetWithCustomKey("ignored-id", "custom")) == "custom"
    assert get_persistence_key(_WidgetWithId("my-widget")) == "my_widget"


@pytest.mark.unit
def test_get_persistence_key_falls_back_to_lowercase_class_name() -> None:
    assert get_persistence_key(_WidgetWithoutId()) == "_widgetwithoutid"

"""Unit tests for TUI state persistence helpers."""

from __future__ import annotations

import json

from teleclaude.cli.tui import state_store


def test_save_and_load_round_trip_namespaced_state(monkeypatch, tmp_path) -> None:
    """Namespaced state should round-trip through tui_state.json."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_store.save_state(
        {
            "sessions": {
                "sticky_sessions": [{"session_id": "sess-1"}],
                "last_output_summary": {"sess-1": {"text": "done", "ts": 0.0}},
            },
            "preparation": {"expanded_todos": ["todo-1"]},
            "status_bar": {"animation_mode": "party", "pane_theming_mode": "highlight2"},
            "app": {"active_tab": "preparation"},
        }
    )

    loaded = state_store.load_state()

    assert loaded["sessions"]["sticky_sessions"] == [{"session_id": "sess-1"}]
    assert loaded["sessions"]["last_output_summary"] == {"sess-1": {"text": "done", "ts": 0.0}}
    assert loaded["preparation"]["expanded_todos"] == ["todo-1"]
    assert loaded["status_bar"]["animation_mode"] == "party"
    assert loaded["status_bar"]["pane_theming_mode"] == "highlight2"
    assert loaded["app"]["active_tab"] == "preparation"


def test_load_migrates_old_flat_state(monkeypatch, tmp_path) -> None:
    """Old flat state should be migrated into namespaced format."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_path.write_text(
        json.dumps(
            {
                "sticky_sessions": [{"session_id": "sess-1"}],
                "expanded_todos": ["todo-1"],
                "input_highlights": ["sess-1"],
                "output_highlights": ["sess-2"],
                "last_output_summary": {"sess-2": {"text": "summary", "ts": 1.0}},
                "collapsed_sessions": ["sess-3"],
                "preview": {"session_id": "sess-2"},
                "animation_mode": "party",
                "pane_theming_mode": "full",
            }
        ),
        encoding="utf-8",
    )

    loaded = state_store.load_state()

    assert loaded["sessions"]["sticky_sessions"] == [{"session_id": "sess-1"}]
    assert loaded["sessions"]["input_highlights"] == ["sess-1"]
    assert loaded["sessions"]["output_highlights"] == ["sess-2"]
    assert loaded["sessions"]["last_output_summary"] == {"sess-2": {"text": "summary", "ts": 1.0}}
    assert loaded["sessions"]["collapsed_sessions"] == ["sess-3"]
    assert loaded["sessions"]["preview"] == {"session_id": "sess-2"}
    assert loaded["preparation"]["expanded_todos"] == ["todo-1"]
    assert loaded["status_bar"]["animation_mode"] == "party"
    assert loaded["status_bar"]["pane_theming_mode"] == "agent_plus"
    assert loaded["app"] == {}


def test_load_missing_file_seeds_status_bar_defaults(monkeypatch, tmp_path) -> None:
    """Missing state file should still seed canonical footer defaults."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)
    monkeypatch.setattr(state_store, "_default_pane_theming_mode", lambda: "off")

    loaded = state_store.load_state()

    assert loaded["status_bar"]["animation_mode"] == "periodic"
    assert loaded["status_bar"]["pane_theming_mode"] == "off"


def test_load_namespaced_state_fills_missing_status_bar_defaults(monkeypatch, tmp_path) -> None:
    """Namespaced state should normalize missing footer fields."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)
    monkeypatch.setattr(state_store, "_default_pane_theming_mode", lambda: "highlight2")

    state_path.write_text(json.dumps({"sessions": {}, "status_bar": {}}), encoding="utf-8")
    loaded = state_store.load_state()

    assert loaded["status_bar"]["animation_mode"] == "periodic"
    assert loaded["status_bar"]["pane_theming_mode"] == "highlight2"


def test_save_state_always_writes_required_namespaces(monkeypatch, tmp_path) -> None:
    """save_state() should always emit required namespaces."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_store.save_state(
        {
            "sessions": {
                "sess-1": {"text": "another summary", "ts": 0.0},
            },
        },
    )

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    for key in ("sessions", "preparation", "status_bar", "app"):
        assert key in raw

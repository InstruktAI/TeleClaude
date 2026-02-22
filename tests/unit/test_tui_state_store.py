"""Unit tests for TUI state persistence helpers."""

from __future__ import annotations

import json

from teleclaude.cli.tui import state_store


def test_save_and_load_persists_last_output_summary(monkeypatch, tmp_path) -> None:
    """last_output_summary map should round-trip through tui_state.json."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    sessions_state = {
        "sticky_sessions": [],
        "input_highlights": [],
        "output_highlights": [],
        "last_output_summary": {
            "sess-1": {"text": "done", "ts": 0.0},
            "sess-2": {"text": "another summary", "ts": 0.0},
        },
        "collapsed_sessions": [],
    }
    state_store.save_state(sessions_state=sessions_state)

    loaded = state_store.load_state()

    assert loaded.last_output_summary == {
        "sess-1": {"text": "done", "ts": 0.0},
        "sess-2": {"text": "another summary", "ts": 0.0},
    }


def test_load_ignores_invalid_last_output_summary_entries(monkeypatch, tmp_path) -> None:
    """Only dict entries with a 'text' key should be loaded into last_output_summary."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_path.write_text(
        json.dumps(
            {
                "last_output_summary": {
                    "ok": {"text": "valid", "ts": 0.0},
                    "old_format": "just a string",
                    "bad_value": 123,
                    "none_value": None,
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = state_store.load_state()

    # Dict with text key → kept; plain string → backward-compat converted; int/None → dropped
    assert "ok" in loaded.last_output_summary
    assert loaded.last_output_summary["ok"]["text"] == "valid"
    assert "old_format" in loaded.last_output_summary
    assert loaded.last_output_summary["old_format"]["text"] == "just a string"
    assert "bad_value" not in loaded.last_output_summary
    assert "none_value" not in loaded.last_output_summary

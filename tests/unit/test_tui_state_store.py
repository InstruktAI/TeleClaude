"""Unit tests for TUI state persistence helpers."""

from __future__ import annotations

import json

from teleclaude.cli.tui import state_store
from teleclaude.cli.tui.state import TuiState


def test_save_and_load_persists_last_output_summary(monkeypatch, tmp_path) -> None:
    """last_output_summary map should round-trip through tui_state.json."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state = TuiState()
    state.sessions.last_output_summary["sess-1"] = "done"
    state.sessions.last_output_summary["sess-2"] = "another summary"

    state_store.save_sticky_state(state)

    loaded = TuiState()
    state_store.load_sticky_state(loaded)

    assert loaded.sessions.last_output_summary == {
        "sess-1": "done",
        "sess-2": "another summary",
    }


def test_load_ignores_invalid_last_output_summary_entries(monkeypatch, tmp_path) -> None:
    """Only string->string entries should be loaded into last_output_summary."""
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_path.write_text(
        json.dumps(
            {
                "last_output_summary": {
                    "ok": "valid",
                    "bad_value": 123,
                    "none_value": None,
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = TuiState()
    state_store.load_sticky_state(loaded)

    assert loaded.sessions.last_output_summary == {"ok": "valid"}

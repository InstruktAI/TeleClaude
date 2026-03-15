from __future__ import annotations

import json
from pathlib import Path

import pytest

from teleclaude.cli.tui import state_store


@pytest.mark.unit
def test_load_state_migrates_flat_payloads_into_namespaced_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "tui_state.json"
    state_path.write_text(
        json.dumps(
            {
                "sticky_sessions": ["s1", "s2"],
                "preview_session_id": "s1",
                "selected_session_id": "s2",
                "animation_mode": "party",
                "pane_theming_mode": "full",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    loaded = state_store.load_state()

    assert loaded == {
        "sessions": {"sticky_sessions": ["s1", "s2"]},
        "preparation": {},
        "status_bar": {"animation_mode": "party", "pane_theming_mode": "agent_plus"},
        "app": {},
    }


@pytest.mark.unit
def test_save_state_jsonifies_sets_and_adds_required_namespaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_store.save_state({"sessions": {"sticky_sessions": {"b", "a"}}, "app": {"animation_mode": "party"}})

    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "sessions": {"sticky_sessions": ["a", "b"]},
        "app": {"animation_mode": "party"},
        "preparation": {},
        "status_bar": {},
    }


@pytest.mark.unit
def test_save_sticky_state_is_currently_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "tui_state.json"
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", state_path)

    state_store.save_sticky_state(object())

    assert state_path.exists() is False

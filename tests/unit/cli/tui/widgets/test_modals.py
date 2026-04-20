"""Characterization tests for teleclaude.cli.tui.widgets.modals."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.api_models import AgentAvailabilityDTO
from teleclaude.cli.tui.widgets.modals import (
    ModeSelector,
    NewProjectModal,
    NewProjectResult,
    SessionIdTypeSelector,
    _is_agent_selectable,
)


def _make_info(
    *,
    available: bool | None = True,
    status: str | None = "available",
    reason: str | None = None,
) -> AgentAvailabilityDTO:
    return AgentAvailabilityDTO(agent="claude", available=available, status=status, reason=reason)


# --- _is_agent_selectable ---


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_info_none() -> None:
    """Absent info means the local cache hasn't loaded yet — selectable by default."""
    assert _is_agent_selectable(None) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_available() -> None:
    info = _make_info(available=True)
    assert _is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_degraded_status() -> None:
    info = _make_info(available=False, status="degraded")
    assert _is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_reason_starts_with_degraded() -> None:
    info = _make_info(available=False, status="unavailable", reason="degraded: cold")
    assert _is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_false_when_unavailable_no_degraded() -> None:
    info = _make_info(available=False, status="unavailable")
    assert _is_agent_selectable(info) is False


# --- ModeSelector ---


@pytest.mark.unit
def test_mode_selector_default_selected_is_slow_index() -> None:
    """Default selected=1 which maps to 'slow' in _MODES."""
    sel = ModeSelector()
    assert sel.selected == 1
    assert sel.selected_mode == "slow"


@pytest.mark.unit
def test_mode_selector_action_next_wraps_around() -> None:
    sel = ModeSelector()
    sel.selected = len(ModeSelector._MODES) - 1
    sel.action_next()
    assert sel.selected == 0


@pytest.mark.unit
def test_mode_selector_action_prev_wraps_around() -> None:
    sel = ModeSelector()
    sel.selected = 0
    sel.action_prev()
    assert sel.selected == len(ModeSelector._MODES) - 1


@pytest.mark.unit
def test_mode_selector_default_mode_returns_string() -> None:
    """'default' selection returns the string 'default' — accepted by the API Literal."""
    sel = ModeSelector()
    default_idx = next(i for i, (k, _) in enumerate(ModeSelector._MODES) if k == "default")
    sel.selected = default_idx
    assert sel.selected_mode == "default"


@pytest.mark.unit
def test_mode_selector_all_modes_return_their_string_value() -> None:
    """Every mode returns its string key unchanged."""
    sel = ModeSelector()
    for i, (key, _) in enumerate(ModeSelector._MODES):
        sel.selected = i
        assert sel.selected_mode == key


# --- SessionIdTypeSelector ---


@pytest.mark.unit
def test_session_id_type_selector_is_importable() -> None:
    assert SessionIdTypeSelector is not None


@pytest.mark.unit
def test_session_id_type_selector_types_has_two_entries() -> None:
    assert len(SessionIdTypeSelector._TYPES) == 2


@pytest.mark.unit
def test_session_id_type_selector_cell_width_is_16() -> None:
    assert SessionIdTypeSelector._CELL_WIDTH == 16


class _FakeInput:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeLabel:
    def __init__(self) -> None:
        self.message = ""

    def update(self, message: str) -> None:
        self.message = message


@pytest.mark.unit
def test_new_project_modal_accepts_missing_directory_path(tmp_path: Path) -> None:
    modal = NewProjectModal(existing_names=set(), existing_paths=set())

    name_input = _FakeInput("gamma")
    desc_input = _FakeInput("new project")
    path_input = _FakeInput(str(tmp_path / "gamma"))
    name_error = _FakeLabel()
    path_error = _FakeLabel()

    def _query_one(selector: str, _expected: object) -> object:
        mapping = {
            "#name-input": name_input,
            "#name-error": name_error,
            "#path-input": path_input,
            "#path-error": path_error,
            "#desc-input": desc_input,
        }
        return mapping[selector]

    with patch.object(modal, "query_one", side_effect=_query_one), patch.object(modal, "dismiss") as dismiss:
        modal._do_create()

    dismiss.assert_called_once()
    result = dismiss.call_args.args[0]
    assert isinstance(result, NewProjectResult)
    assert result.name == "gamma"
    assert result.description == "new project"
    assert result.path == str((tmp_path / "gamma").resolve())


@pytest.mark.unit
def test_new_project_modal_rejects_existing_file_path(tmp_path: Path) -> None:
    modal = NewProjectModal(existing_names=set(), existing_paths=set())
    target = tmp_path / "gamma"
    target.write_text("not a directory", encoding="utf-8")

    name_input = _FakeInput("gamma")
    desc_input = _FakeInput("")
    path_input = _FakeInput(str(target))
    name_error = _FakeLabel()
    path_error = _FakeLabel()

    def _query_one(selector: str, _expected: object) -> object:
        mapping = {
            "#name-input": name_input,
            "#name-error": name_error,
            "#path-input": path_input,
            "#path-error": path_error,
            "#desc-input": desc_input,
        }
        return mapping[selector]

    with patch.object(modal, "query_one", side_effect=_query_one), patch.object(modal, "dismiss") as dismiss:
        modal._do_create()

    dismiss.assert_not_called()

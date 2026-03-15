from __future__ import annotations

import pytest

from teleclaude.cli.tui._pane_specs import LAYOUT_SPECS, ComputerInfo, PaneState


@pytest.mark.unit
def test_computer_info_distinguishes_local_and_remote_targets() -> None:
    local = ComputerInfo(name="local", is_local=True)
    remote = ComputerInfo(name="remote", is_local=False, user="alice", host="example.test")

    assert local.is_remote is False
    assert local.ssh_target is None
    assert remote.is_remote is True
    assert remote.ssh_target == "alice@example.test"


@pytest.mark.unit
def test_pane_state_defaults_to_no_active_session_or_mappings() -> None:
    state = PaneState()

    assert state.session_to_pane == {}
    assert state.active_session_id is None


@pytest.mark.unit
def test_layout_specs_match_declared_row_and_column_dimensions() -> None:
    observed_keys = sorted(LAYOUT_SPECS)

    assert observed_keys == [1, 2, 3, 4, 5, 6]
    for key, spec in LAYOUT_SPECS.items():
        assert len(spec.grid) == spec.rows, key
        assert {len(row) for row in spec.grid} == {spec.cols}, key

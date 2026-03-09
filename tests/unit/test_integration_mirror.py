"""Unit tests for integration phase mirroring to per-todo state.yaml."""

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.integration.state_machine import _mirror_integration_phase


def test_mirror_writes_integration_phase(tmp_path: Path) -> None:
    """_mirror_integration_phase writes integration_phase to state.yaml."""
    todos_dir = tmp_path / "todos" / "my-slug"
    todos_dir.mkdir(parents=True)
    (todos_dir / "state.yaml").write_text(yaml.dump({"build": "pending"}))

    _mirror_integration_phase(str(tmp_path), "my-slug", "merge_clean")

    state = yaml.safe_load((todos_dir / "state.yaml").read_text())
    assert state["integration_phase"] == "merge_clean"


def test_mirror_creates_state_file_when_absent(tmp_path: Path) -> None:
    """_mirror_integration_phase creates state.yaml if it doesn't exist."""
    todos_dir = tmp_path / "todos" / "new-slug"
    todos_dir.mkdir(parents=True)

    _mirror_integration_phase(str(tmp_path), "new-slug", "candidate_dequeued")

    state_file = todos_dir / "state.yaml"
    assert state_file.exists()
    state = yaml.safe_load(state_file.read_text())
    assert state["integration_phase"] == "candidate_dequeued"


def test_mirror_preserves_existing_state_fields(tmp_path: Path) -> None:
    """_mirror_integration_phase preserves other fields in state.yaml."""
    todos_dir = tmp_path / "todos" / "my-slug"
    todos_dir.mkdir(parents=True)
    (todos_dir / "state.yaml").write_text(yaml.dump({"build": "complete", "dor": {"score": 9}}))

    _mirror_integration_phase(str(tmp_path), "my-slug", "push_succeeded")

    state = yaml.safe_load((todos_dir / "state.yaml").read_text())
    assert state["build"] == "complete"
    assert state["integration_phase"] == "push_succeeded"


def test_mirror_does_not_raise_on_failure(tmp_path: Path) -> None:
    """_mirror_integration_phase is best-effort — does not propagate exceptions."""
    with patch("teleclaude.core.integration.state_machine.read_phase_state", side_effect=OSError("disk full")):
        # Should not raise
        _mirror_integration_phase(str(tmp_path), "my-slug", "merge_clean")

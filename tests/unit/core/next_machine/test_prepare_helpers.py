"""Tests for Task 2: prepare_helpers module — artifact lifecycle helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine._types import StateValue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    return str(tmp_path), slug


def _write_file(todo_dir: Path, name: str, content: str = "content") -> Path:
    p = todo_dir / name
    p.write_text(content)
    return p


def _read_state(cwd: str, slug: str) -> dict[str, StateValue]:
    state_path = Path(cwd) / "todos" / slug / "state.yaml"
    if not state_path.exists():
        return {}
    return yaml.safe_load(state_path.read_text()) or {}


# ---------------------------------------------------------------------------
# artifact_digest
# ---------------------------------------------------------------------------


def test_artifact_digest_returns_sha256_for_existing_file(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import artifact_digest

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md", "hello")

    result = artifact_digest(cwd, slug, "input.md")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert result == expected


def test_artifact_digest_returns_empty_for_missing_file(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import artifact_digest

    cwd, slug = _make_todo(tmp_path)
    assert artifact_digest(cwd, slug, "nonexistent.md") == ""


# ---------------------------------------------------------------------------
# record_artifact_produced
# ---------------------------------------------------------------------------


def test_record_artifact_produced_writes_digest_and_produced_at(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import record_artifact_produced

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md", "my input")
    expected_digest = hashlib.sha256(b"my input").hexdigest()

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")

    state = _read_state(cwd, slug)
    artifacts = state.get("artifacts", {})
    assert artifacts["input"]["digest"] == expected_digest
    assert artifacts["input"]["produced_at"] != ""


# ---------------------------------------------------------------------------
# check_artifact_staleness
# ---------------------------------------------------------------------------


def test_check_artifact_staleness_no_changes_returns_empty(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import check_artifact_staleness, record_artifact_produced

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md", "hello")

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")

    result = check_artifact_staleness(cwd, slug)
    assert result == []


def test_check_artifact_staleness_detects_changed_input(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import check_artifact_staleness, record_artifact_produced

    cwd, slug = _make_todo(tmp_path)
    input_file = _write_file(tmp_path / "todos" / slug, "input.md", "original")
    _write_file(tmp_path / "todos" / slug, "requirements.md", "reqs")

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")
        record_artifact_produced(cwd, slug, "requirements.md")

    # Modify input after recording
    input_file.write_text("changed content")

    result = check_artifact_staleness(cwd, slug)
    # Input and all downstream (requirements, implementation_plan) should be stale
    assert "input" in result
    assert "requirements" in result


def test_check_artifact_staleness_only_requirements_stale(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import check_artifact_staleness, record_artifact_produced

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md", "stable input")
    reqs_file = _write_file(tmp_path / "todos" / slug, "requirements.md", "original reqs")
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md", "plan")

    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        record_artifact_produced(cwd, slug, "input.md")
        record_artifact_produced(cwd, slug, "requirements.md")
        record_artifact_produced(cwd, slug, "implementation-plan.md")

    # Only modify requirements
    reqs_file.write_text("changed reqs")

    result = check_artifact_staleness(cwd, slug)
    assert "input" not in result
    assert "requirements" in result
    assert "implementation_plan" in result


# ---------------------------------------------------------------------------
# compute_artifact_diff
# ---------------------------------------------------------------------------


def test_compute_artifact_diff_returns_empty_when_base_sha_empty(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import compute_artifact_diff

    cwd, slug = _make_todo(tmp_path)
    result = compute_artifact_diff(cwd, slug, "todos/test-slug/requirements.md", "")
    assert result == ""


def test_compute_artifact_diff_returns_diff_output(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import compute_artifact_diff

    cwd, slug = _make_todo(tmp_path)

    with patch("teleclaude.core.next_machine.prepare_helpers._run_git_prepare") as mock_git:
        mock_git.return_value = (0, "diff content", "")
        result = compute_artifact_diff(cwd, slug, "todos/test-slug/requirements.md", "abc123")

    assert result == "diff content"


def test_compute_todo_folder_diff_returns_folder_diff(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.prepare_helpers import compute_todo_folder_diff

    cwd, slug = _make_todo(tmp_path)

    with patch("teleclaude.core.next_machine.prepare_helpers._run_git_prepare") as mock_git:
        mock_git.return_value = (0, "folder diff", "")
        result = compute_todo_folder_diff(cwd, slug, "abc123")

    assert result == "folder diff"
    call_args = mock_git.call_args[0][0]
    assert f"todos/{slug}/" in " ".join(call_args)

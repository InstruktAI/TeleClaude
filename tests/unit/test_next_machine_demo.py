"""Unit tests for demo artifacts and CLI runner."""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from teleclaude.cli.telec import _handle_todo_demo

# =============================================================================
# Demo Artifact Spec Tests
# =============================================================================


def test_demo_artifact_spec_exists():
    """Verify demo-artifact spec doc exists at the expected path."""
    spec_path = Path(__file__).parents[2] / "docs" / "project" / "spec" / "demo-artifact.md"
    assert spec_path.exists(), f"Demo artifact spec not found at {spec_path}"


def test_demos_directory_exists():
    """Verify demos/ directory exists at repository root."""
    demos_path = Path(__file__).parents[2] / "demos"
    assert demos_path.exists(), f"demos/ directory not found at {demos_path}"


def _make_snapshot(
    overrides: dict[str, Any] | None = None,  # guard: loose-dict - param for test fixture override
) -> dict[str, Any]:  # guard: loose-dict-func - test helper needs flexibility for various snapshot fixtures
    """Build a valid snapshot.json for testing."""
    base: dict[str, Any] = {  # guard: loose-dict - matches function return type
        "slug": "test-feature",
        "title": "Test Feature Delivery",
        "version": "0.1.0",
        "delivered": "2026-02-21",
        "commit": "abc1234",
        "demo": "echo 'Demo output'",
        "metrics": {
            "commits": 5,
            "files_changed": 10,
            "files_created": 3,
            "tests_added": 2,
            "tests_passing": 42,
            "review_rounds": 1,
            "findings_resolved": 3,
            "lines_added": 200,
            "lines_removed": 50,
        },
        "acts": {
            "challenge": "Users needed a way to celebrate deliveries.",
            "build": "We added artifact storage with semver gating.",
            "gauntlet": "One critical finding resolved in round 1.",
            "whats_next": "Consider adding replay capability.",
        },
    }
    if overrides:
        base.update(overrides)
    return base


SNAPSHOT_REQUIRED_FIELDS = {
    "slug": str,
    "title": str,
    "version": str,
    "delivered": str,
    "commit": str,
    "metrics": dict,
    "acts": dict,
}

METRICS_REQUIRED_FIELDS = {
    "commits": int,
    "files_changed": int,
    "files_created": int,
    "tests_added": int,
    "tests_passing": int,
    "review_rounds": int,
    "findings_resolved": int,
    "lines_added": int,
    "lines_removed": int,
}

ACTS_REQUIRED_FIELDS = {
    "challenge": str,
    "build": str,
    "gauntlet": str,
    "whats_next": str,
}


def test_snapshot_schema_required_fields():
    """Verify snapshot.json contains all required top-level fields with correct types."""
    snapshot = _make_snapshot()
    for field, expected_type in SNAPSHOT_REQUIRED_FIELDS.items():
        assert field in snapshot, f"Missing required field: {field}"
        assert isinstance(snapshot[field], expected_type), (
            f"Field {field} should be {expected_type.__name__}, got {type(snapshot[field]).__name__}"
        )


def test_snapshot_schema_demo_field_optional():
    """Verify demo field is optional (backward compatibility)."""
    snapshot = _make_snapshot()
    del snapshot["demo"]
    # Should still be valid without demo field
    for field in SNAPSHOT_REQUIRED_FIELDS:
        assert field in snapshot


def test_snapshot_schema_metrics_fields():
    """Verify metrics object contains all required fields with correct types."""
    snapshot = _make_snapshot()
    metrics = snapshot["metrics"]
    for field, expected_type in METRICS_REQUIRED_FIELDS.items():
        assert field in metrics, f"Missing metrics field: {field}"
        assert isinstance(metrics[field], expected_type), f"Metrics field {field} should be {expected_type.__name__}"


def test_snapshot_schema_acts_fields():
    """Verify acts object contains all required fields with correct types."""
    snapshot = _make_snapshot()
    acts = snapshot["acts"]
    for field, expected_type in ACTS_REQUIRED_FIELDS.items():
        assert field in acts, f"Missing acts field: {field}"
        assert isinstance(acts[field], expected_type), f"Acts field {field} should be {expected_type.__name__}"


def test_snapshot_roundtrip_json():
    """Verify snapshot can be serialized and deserialized without loss."""
    snapshot = _make_snapshot()
    serialized = json.dumps(snapshot)
    deserialized = json.loads(serialized)
    assert deserialized == snapshot


# =============================================================================
# Demo Artifact Structure Tests
# =============================================================================


def test_demo_artifact_structure():
    """Verify a demo artifact folder contains snapshot.json with slug-based naming."""
    with tempfile.TemporaryDirectory() as tmpdir:
        demo_dir = Path(tmpdir) / "demos" / "test-slug"
        demo_dir.mkdir(parents=True)

        # Write snapshot.json
        snapshot = _make_snapshot()
        (demo_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))

        # Verify structure (no demo.sh required)
        assert (demo_dir / "snapshot.json").exists()
        assert demo_dir.name == "test-slug"  # slug-based naming


# =============================================================================
# CLI Runner Tests (unit tests calling _handle_todo_demo directly)
# =============================================================================


def test_cli_demo_list_empty_directory(tmp_path: Path, capsys):
    """CLI runner handles empty demos directory gracefully."""
    demos_dir = tmp_path / "demos"
    demos_dir.mkdir()

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo([])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "No demos available" in captured.out


def test_cli_demo_list_shows_available_demos(tmp_path: Path, capsys):
    """CLI runner lists available demos when no slug provided."""
    demos_dir = tmp_path / "demos"
    (demos_dir / "test-slug").mkdir(parents=True)
    snapshot = _make_snapshot()
    (demos_dir / "test-slug" / "snapshot.json").write_text(json.dumps(snapshot))

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo([])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "test-slug" in captured.out
    assert "Test Feature Delivery" in captured.out


def test_cli_demo_run_nonexistent_slug(tmp_path: Path, capsys):
    """CLI runner exits with error for nonexistent slug."""
    demos_dir = tmp_path / "demos"
    (demos_dir / "existing-slug").mkdir(parents=True)
    snapshot = _make_snapshot()
    (demos_dir / "existing-slug" / "snapshot.json").write_text(json.dumps(snapshot))

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["nonexistent"])
        except SystemExit as e:
            assert e.code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.out.lower()


def test_cli_demo_run_missing_demo_field(tmp_path: Path, capsys):
    """CLI runner warns and exits cleanly when demo field is missing."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot()
    del snapshot["demo"]
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["test-slug"])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "no 'demo' field" in captured.out.lower() or "skipping" in captured.out.lower()


def test_cli_demo_run_semver_gate_incompatible(tmp_path: Path, capsys):
    """CLI runner skips demo with incompatible major version."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot({"version": "0.1.0"})
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))

    # Different major version
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["test-slug"])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "incompatible" in captured.out.lower() or "mismatch" in captured.out.lower()


def test_cli_demo_run_semver_gate_compatible(tmp_path: Path, capsys):
    """CLI runner executes demo when major version matches."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot({"version": "0.1.0", "demo": "echo 'Demo executed'"})
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))

    # Matching major version
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["test-slug"])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "Running demo: test-slug" in captured.out

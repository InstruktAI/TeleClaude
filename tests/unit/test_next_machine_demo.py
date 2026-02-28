"""Unit tests for demo artifacts and CLI runner."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from teleclaude.cli.telec import (
    _check_no_demo_marker,
    _demo_create,
    _demo_validate,
    _extract_demo_blocks,
    _handle_todo_demo,
)

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


# =============================================================================
# Code Block Extraction Tests
# =============================================================================


def test_extract_demo_blocks_basic():
    """Extract simple bash code blocks from demo.md content."""
    content = """# Demo

Some text.

```bash
echo "hello"
```

More text.

```bash
echo "world"
```
"""
    blocks = _extract_demo_blocks(content)
    assert len(blocks) == 2
    assert blocks[0][1].strip() == 'echo "hello"'
    assert blocks[0][2] is False  # not skipped
    assert blocks[1][1].strip() == 'echo "world"'


def test_extract_demo_blocks_skip_validation():
    """Skip-validation annotation marks blocks as skipped."""
    content = """# Demo

<!-- skip-validation: requires visual confirmation -->
```bash
open http://localhost:3000
```

```bash
echo "this runs"
```
"""
    blocks = _extract_demo_blocks(content)
    assert len(blocks) == 2
    assert blocks[0][2] is True  # skipped
    assert "visual confirmation" in blocks[0][3]
    assert blocks[1][2] is False  # not skipped


def test_extract_demo_blocks_no_blocks():
    """No code blocks returns empty list."""
    content = """# Demo

Just guided steps. No code blocks here.
"""
    blocks = _extract_demo_blocks(content)
    assert blocks == []


def test_extract_demo_blocks_non_bash_ignored():
    """Non-bash fenced blocks are not extracted."""
    content = """# Demo

```python
print("ignored")
```

```bash
echo "extracted"
```
"""
    blocks = _extract_demo_blocks(content)
    assert len(blocks) == 1
    assert blocks[0][1].strip() == 'echo "extracted"'


# =============================================================================
# demo.md CLI Runner Tests
# =============================================================================


def test_cli_demo_prefers_demo_md_over_snapshot(tmp_path: Path, capsys):
    """CLI runner prefers demo.md over snapshot.json demo field."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot({"version": "0.1.0", "demo": "echo 'snapshot demo'"})
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))
    (demos_dir / "demo.md").write_text('# Demo\n\n```bash\necho "demo.md wins"\n```\n')

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["run", "test-slug"])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "running demo" in captured.out.lower()
    assert "PASS" in captured.out


def test_cli_demo_finds_demo_md_in_todos(tmp_path: Path, capsys):
    """CLI runner finds demo.md in todos/{slug}/ during build phase."""
    # Create demos dir with snapshot but no demo.md
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot({"version": "0.1.0"})
    del snapshot["demo"]
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))

    # Create demo.md in todos
    todos_dir = tmp_path / "todos" / "test-slug"
    todos_dir.mkdir(parents=True)
    (todos_dir / "demo.md").write_text('# Demo\n\n```bash\necho "from todos"\n```\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["run", "test-slug"])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "todos/test-slug/demo.md" in captured.out
    assert "PASS" in captured.out


def test_cli_demo_run_no_blocks_exits_one(tmp_path: Path, capsys):
    """demo.md with no code blocks exits 1 (silent-pass fix)."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot({"version": "0.1.0"})
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))
    (demos_dir / "demo.md").write_text("# Demo\n\nJust guided steps.\n")

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["run", "test-slug"])
        except SystemExit as e:
            assert e.code == 1
    captured = capsys.readouterr()
    assert "no executable blocks" in captured.out.lower()


def test_cli_demo_failing_block_exits_one(tmp_path: Path, capsys):
    """demo.md with a failing code block exits 1."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = _make_snapshot({"version": "0.1.0"})
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))
    (demos_dir / "demo.md").write_text("# Demo\n\n```bash\nexit 1\n```\n")

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["run", "test-slug"])
        except SystemExit as e:
            assert e.code == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.out


# =============================================================================
# Validate Subcommand Tests
# =============================================================================


def test_validate_exits_zero_with_bash_blocks(tmp_path: Path, capsys):
    """validate exits 0 when demo.md has bash blocks."""
    (tmp_path / "todos" / "test-slug").mkdir(parents=True)
    (tmp_path / "todos" / "test-slug" / "demo.md").write_text("# Demo\n\n```bash\necho hello\n```\n")

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _demo_validate("test-slug", tmp_path)
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "validation passed" in captured.out.lower()


def test_validate_exits_one_on_scaffold_template(tmp_path: Path, capsys):
    """validate exits 1 on scaffold template (no blocks)."""
    (tmp_path / "todos" / "test-slug").mkdir(parents=True)
    (tmp_path / "todos" / "test-slug" / "demo.md").write_text(
        "# Demo: test-slug\n\n## Validation\n\n"
        "<!-- Bash code blocks that prove the feature works. -->\n\n"
        "## Guided Presentation\n\n"
        "<!-- Walk through the delivery step by step. -->\n"
    )

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _demo_validate("test-slug", tmp_path)
        except SystemExit as e:
            assert e.code == 1
    captured = capsys.readouterr()
    assert "no executable bash blocks" in captured.out.lower()


def test_validate_exits_zero_on_no_demo_marker(tmp_path: Path, capsys):
    """validate exits 0 on <!-- no-demo: reason --> and captures reason."""
    (tmp_path / "todos" / "test-slug").mkdir(parents=True)
    (tmp_path / "todos" / "test-slug" / "demo.md").write_text(
        "# Demo\n\n<!-- no-demo: infrastructure change, not demonstrable -->\n\n"
        "This delivery modifies internal wiring only.\n"
    )

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _demo_validate("test-slug", tmp_path)
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "no-demo marker" in captured.out.lower()
    assert "infrastructure change" in captured.out.lower()


def test_cli_demo_validate_does_not_require_runtime_config_agents(tmp_path: Path):
    """`telec todo demo validate` should work even if runtime config is invalid."""
    slug = "test-slug"
    demo_dir = tmp_path / "todos" / slug
    demo_dir.mkdir(parents=True)
    (demo_dir / "demo.md").write_text("# Demo\n\n```bash\necho ok\n```\n", encoding="utf-8")

    invalid_config = tmp_path / "invalid-config.yml"
    invalid_config.write_text("computer:\n  name: test\n", encoding="utf-8")

    env = os.environ.copy()
    env["TELECLAUDE_CONFIG_PATH"] = str(invalid_config)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "teleclaude.cli.telec",
            "todo",
            "demo",
            "validate",
            slug,
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Validation passed" in result.stdout


# =============================================================================
# Run Subcommand Tests
# =============================================================================


def test_run_exits_one_on_scaffold_template(tmp_path: Path, capsys):
    """run exits 1 on scaffold template (no blocks) — the silent-pass fix."""
    (tmp_path / "todos" / "test-slug").mkdir(parents=True)
    (tmp_path / "todos" / "test-slug" / "demo.md").write_text(
        "# Demo: test-slug\n\n## Validation\n\n<!-- Bash code blocks. -->\n\n## Guided Presentation\n"
    )

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["run", "test-slug"])
        except SystemExit as e:
            assert e.code == 1
    captured = capsys.readouterr()
    assert "no executable blocks" in captured.out.lower()


def test_run_executes_blocks_and_reports(tmp_path: Path, capsys):
    """run executes blocks and reports pass/fail."""
    (tmp_path / "todos" / "test-slug").mkdir(parents=True)
    (tmp_path / "todos" / "test-slug" / "demo.md").write_text(
        '# Demo\n\n```bash\necho "hello"\n```\n\n```bash\necho "world"\n```\n'
    )

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo(["run", "test-slug"])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "PASS" in captured.out
    assert "2/2 blocks" in captured.out


# =============================================================================
# Create Subcommand Tests
# =============================================================================


def test_create_promotes_demo_md(tmp_path: Path, capsys):
    """create promotes demo.md to demos/{slug}/ with snapshot.json."""
    (tmp_path / "todos" / "test-slug").mkdir(parents=True)
    (tmp_path / "todos" / "test-slug" / "demo.md").write_text("# Demo: Test Feature\n\n```bash\necho ok\n```\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _demo_create("test-slug", tmp_path)
        except SystemExit as e:
            assert e.code == 0

    # Verify demo.md was copied
    assert (tmp_path / "demos" / "test-slug" / "demo.md").exists()

    # Verify snapshot.json
    snapshot = json.loads((tmp_path / "demos" / "test-slug" / "snapshot.json").read_text())
    assert snapshot["slug"] == "test-slug"
    assert snapshot["title"] == "Test Feature"
    assert snapshot["version"] == "1.2.3"


def test_create_fails_when_source_missing(tmp_path: Path, capsys):
    """create fails when source demo.md doesn't exist."""
    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _demo_create("nonexistent", tmp_path)
        except SystemExit as e:
            assert e.code == 1
    captured = capsys.readouterr()
    assert "no demo.md found" in captured.out.lower()


# =============================================================================
# Listing Tests
# =============================================================================


def test_no_subcommand_listing_still_works(tmp_path: Path, capsys):
    """telec todo demo (no args) lists available demos."""
    demos_dir = tmp_path / "demos" / "test-slug"
    demos_dir.mkdir(parents=True)
    snapshot = {"slug": "test-slug", "title": "Test Feature", "version": "1.0.0"}
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot))

    with patch("teleclaude.cli.telec.Path.cwd", return_value=tmp_path):
        try:
            _handle_todo_demo([])
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "test-slug" in captured.out
    assert "Test Feature" in captured.out


# =============================================================================
# No-demo marker unit test
# =============================================================================


def test_check_no_demo_marker_found():
    """_check_no_demo_marker detects the marker and returns reason."""
    content = "# Demo\n\n<!-- no-demo: testing only -->\n\nSome text.\n"
    assert _check_no_demo_marker(content) == "testing only"


def test_check_no_demo_marker_not_found():
    """_check_no_demo_marker returns None when no marker present."""
    content = "# Demo\n\n```bash\necho ok\n```\n"
    assert _check_no_demo_marker(content) is None

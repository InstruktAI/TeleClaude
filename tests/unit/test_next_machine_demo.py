"""Unit tests for demo phase integration in the next machine."""

import json
import tempfile
from pathlib import Path

from teleclaude.core.next_machine.core import POST_COMPLETION, format_tool_call

# =============================================================================
# POST_COMPLETION Demo Wiring Tests
# =============================================================================


def test_post_completion_has_next_demo_entry():
    """POST_COMPLETION dict includes a next-demo handler."""
    assert "next-demo" in POST_COMPLETION


def test_post_completion_next_demo_has_end_session():
    """next-demo post-completion instructs ending the worker session."""
    template = POST_COMPLETION["next-demo"]
    assert "end_session" in template


def test_post_completion_finalize_includes_demo_step():
    """next-finalize post-completion includes a DEMO dispatch step."""
    template = POST_COMPLETION["next-finalize"]
    assert "DEMO" in template
    assert "next-demo" in template


def test_post_completion_finalize_demo_before_cleanup():
    """Demo step appears before CLEANUP in finalize post-completion."""
    template = POST_COMPLETION["next-finalize"]
    demo_pos = template.index("DEMO")
    cleanup_pos = template.index("CLEANUP")
    assert demo_pos < cleanup_pos


def test_post_completion_finalize_demo_is_non_blocking():
    """Demo step instructs non-blocking behavior on failure."""
    template = POST_COMPLETION["next-finalize"]
    assert "warning" in template.lower() or "fail" in template.lower()
    assert "continue" in template.lower()


def test_format_tool_call_demo_produces_valid_dispatch():
    """format_tool_call with next-demo produces a valid dispatch script."""
    result = format_tool_call(
        command="next-demo",
        args="test-slug",
        project="/tmp/project",
        guidance="Mock guidance",
        subfolder="",
        next_call="",
    )
    assert 'command="/next-demo"' in result
    assert 'args="test-slug"' in result
    assert "teleclaude__run_agent_command(" in result


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


def _make_snapshot(overrides=None):
    """Build a valid snapshot.json for testing."""
    base = {
        "slug": "test-feature",
        "title": "Test Feature Delivery",
        "sequence": 1,
        "version": "0.1.0",
        "delivered": "2026-02-21",
        "commit": "abc1234",
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
    "sequence": int,
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
    """Verify a demo artifact folder contains the expected files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        demo_dir = Path(tmpdir) / "demos" / "001-test-slug"
        demo_dir.mkdir(parents=True)

        # Write snapshot.json
        snapshot = _make_snapshot()
        (demo_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))

        # Write demo.sh
        demo_sh = demo_dir / "demo.sh"
        demo_sh.write_text("#!/usr/bin/env bash\necho 'demo'\n")
        demo_sh.chmod(0o755)

        # Verify structure
        assert (demo_dir / "snapshot.json").exists()
        assert (demo_dir / "demo.sh").exists()
        assert (demo_dir / "demo.sh").stat().st_mode & 0o111  # executable


# =============================================================================
# demo.sh Semver Gate Tests
# =============================================================================


def _create_demo_sh(demo_dir: Path, snapshot_version: str = "0.1.0") -> Path:
    """Create a demo.sh with semver gate logic for testing."""
    snapshot = _make_snapshot({"version": snapshot_version})
    (demo_dir / "snapshot.json").write_text(json.dumps(snapshot))

    # Write a helper Python script alongside for version extraction
    helper = demo_dir / "_version_helper.py"
    helper.write_text(
        "import json, re, sys\n"
        "cmd = sys.argv[1]\n"
        "path = sys.argv[2]\n"
        "if cmd == 'snapshot':\n"
        "    print(json.load(open(path))['version'])\n"
        "elif cmd == 'pyproject':\n"
        "    with open(path) as f:\n"
        '        m = re.search(r\'version\\s*=\\s*"([^"]+)"\', f.read())\n'
        "        print(m.group(1) if m else '0.0.0')\n"
    )

    script = """\
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SNAPSHOT="$SCRIPT_DIR/snapshot.json"
HELPER="$SCRIPT_DIR/_version_helper.py"

if [ ! -f "$SNAPSHOT" ]; then
    echo "ERROR: snapshot.json not found" >&2
    exit 1
fi

DEMO_VERSION="$(python3 "$HELPER" snapshot "$SNAPSHOT")"
DEMO_MAJOR="${DEMO_VERSION%%.*}"

SEARCH_DIR="$SCRIPT_DIR"
CURRENT_VERSION="0.0.0"
while [ "$SEARCH_DIR" != "/" ]; do
    if [ -f "$SEARCH_DIR/pyproject.toml" ]; then
        CURRENT_VERSION="$(python3 "$HELPER" pyproject "$SEARCH_DIR/pyproject.toml")"
        break
    fi
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
done
CURRENT_MAJOR="${CURRENT_VERSION%%.*}"

if [ "$DEMO_MAJOR" != "$CURRENT_MAJOR" ]; then
    echo "Demo from v${DEMO_VERSION} is incompatible with current v${CURRENT_VERSION} (major version mismatch). Skipping."
    exit 0
fi

echo "Demo: ${DEMO_VERSION}"
"""
    demo_sh = demo_dir / "demo.sh"
    demo_sh.write_text(script)
    demo_sh.chmod(0o755)
    return demo_sh


def test_demo_sh_semver_compatible(tmp_path: Path):
    """demo.sh runs successfully when major versions match."""
    demo_dir = tmp_path / "demos" / "001-test"
    demo_dir.mkdir(parents=True)
    _create_demo_sh(demo_dir, "0.1.0")

    # Create a pyproject.toml with matching major version
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')

    import subprocess

    result = subprocess.run(
        ["bash", str(demo_dir / "demo.sh")],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "Demo: 0.1.0" in result.stdout


def test_demo_sh_semver_incompatible(tmp_path: Path):
    """demo.sh exits cleanly with message on major version mismatch."""
    demo_dir = tmp_path / "demos" / "001-test"
    demo_dir.mkdir(parents=True)
    _create_demo_sh(demo_dir, "0.1.0")

    # Create a pyproject.toml with different major version
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')

    import subprocess

    result = subprocess.run(
        ["bash", str(demo_dir / "demo.sh")],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "incompatible" in result.stdout.lower() or "mismatch" in result.stdout.lower()


def test_demo_sh_missing_pyproject_fallback(tmp_path: Path):
    """demo.sh falls back to version 0.0.0 when pyproject.toml is not found."""
    demo_dir = tmp_path / "demos" / "001-test"
    demo_dir.mkdir(parents=True)
    _create_demo_sh(demo_dir, "0.1.0")

    # No pyproject.toml created - should fallback to 0.0.0

    import subprocess

    result = subprocess.run(
        ["bash", str(demo_dir / "demo.sh")],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    # Both have major version 0, so should run
    assert "Demo: 0.1.0" in result.stdout


def test_demo_sh_missing_snapshot_exits_with_error(tmp_path: Path):
    """demo.sh exits with error when snapshot.json is missing."""
    demo_dir = tmp_path / "demos" / "001-test"
    demo_dir.mkdir(parents=True)

    # Create demo.sh but no snapshot.json
    demo_sh = demo_dir / "demo.sh"
    demo_sh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'SNAPSHOT="$SCRIPT_DIR/snapshot.json"\n'
        'if [ ! -f "$SNAPSHOT" ]; then\n'
        '    echo "ERROR: snapshot.json not found" >&2\n'
        "    exit 1\n"
        "fi\n"
    )
    demo_sh.chmod(0o755)

    import subprocess

    result = subprocess.run(
        ["bash", str(demo_sh)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 1
    assert "snapshot.json not found" in result.stderr

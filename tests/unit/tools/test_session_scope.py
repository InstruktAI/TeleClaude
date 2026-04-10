# guard: no-companion
"""Test spec (xfail) for tools/session_scope.py.

All tests are marked xfail — they document the behavioral contract and fail
cleanly before implementation. Remove ``pytestmark = pytest.mark.xfail``
(or per-test markers) once all tests pass after implementation.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(10)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "tools" / "session_scope.py"


def _import_session_scope():
    """Import tools/session_scope as a module for direct function testing."""
    spec = importlib.util.spec_from_file_location("session_scope", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_no_session(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the script with a clean TMPDIR that has no session identity file."""
    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as empty_tmpdir:
        env["TMPDIR"] = empty_tmpdir
        env.pop("TMP", None)
        env.pop("TEMP", None)
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )


def _run_with_fake_session(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the script with a fake session identity file in TMPDIR."""
    import json  # pylint: disable=import-outside-toplevel

    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake session identity file
        identity_file = Path(tmpdir) / "teleclaude_identity.json"
        identity_file.write_text(json.dumps({"session_id": "fake-session-for-test"}))
        env["TMPDIR"] = tmpdir
        env.pop("TMP", None)
        env.pop("TEMP", None)
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )


def test_script_exists() -> None:
    """tools/session_scope.py must exist before any behavioral assertions apply."""
    assert _SCRIPT.exists(), "tools/session_scope.py has not been created"


def test_no_session_exits_2_with_empty_stdout() -> None:
    """Without a session identity file, exit 2 and stdout is empty."""
    assert _SCRIPT.exists(), "tools/session_scope.py not yet implemented"
    result = _run_no_session("--mode", "lint")
    assert result.returncode == 2, f"Expected exit 2, got {result.returncode}; stderr: {result.stderr!r}"
    assert result.stdout.strip() == ""
    # Distinguish from Python "can't open file" error
    assert "can't open file" not in result.stderr


def test_lint_mode_excludes_non_python_files() -> None:
    """Lint mode: .md, .yaml, and .sh touched files are absent from stdout."""
    assert _SCRIPT.exists(), "tools/session_scope.py not yet implemented"
    result = _run("--mode", "lint")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        assert line.endswith(".py") or line.endswith(".pyi"), f"Non-Python file in lint output: {line!r}"


def test_test_mode_maps_source_files_to_companions() -> None:
    """Test mode: teleclaude/x/y.py maps to tests/unit/x/test_y.py in output."""
    assert _SCRIPT.exists(), "tools/session_scope.py not yet implemented"
    result = _run("--mode", "test")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        p = Path(line)
        if "tests/" not in line:
            pytest.fail(f"Output line outside tests/ prefix: {line!r}")
        assert p.name.startswith("test_"), f"Test companion name does not start with 'test_': {p.name!r}"


def test_test_mode_includes_touched_test_files_directly() -> None:
    """Test mode: files already under tests/ appear in output without remapping."""
    assert _SCRIPT.exists(), "tools/session_scope.py not yet implemented"
    result = _run("--mode", "test")
    # All output paths must resolve to existing files on disk.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        assert (_REPO_ROOT / line).exists(), f"Output path does not exist on disk: {line!r}"


def test_collection_failure_exits_3_with_stderr_diagnostic() -> None:
    """When _collect_session_touched_files raises, exit 3 with diagnostic on stderr."""
    assert _SCRIPT.exists(), "tools/session_scope.py not yet implemented"
    # Behavioral contract: error path → exit code 3 (not 1 or 2), non-empty stderr.
    # Activated with an injected session ID pointing to a nonexistent session in the DB.
    result = _run_with_fake_session("--mode", "lint")
    assert result.returncode == 3, f"Expected exit 3, got {result.returncode}"
    assert result.stderr.strip() != "", "Expected diagnostic on stderr, got none"


def _raise_runtime_error(path: str) -> set[str]:
    raise RuntimeError("db connection lost")


def test_non_valueerror_collection_failure_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-ValueError exceptions from collection must also yield exit 3, not an uncaught traceback."""
    mod = _import_session_scope()
    monkeypatch.setattr(sys, "argv", ["session_scope.py", "--mode", "lint"])
    monkeypatch.setattr(mod, "get_session_id", lambda: "fake-session-id")
    monkeypatch.setattr(mod, "_collect_session_touched_files", _raise_runtime_error)
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 3


def test_missing_companion_is_silently_skipped() -> None:
    """Test mode: source files whose companion does not exist are omitted from output."""
    assert _SCRIPT.exists(), "tools/session_scope.py not yet implemented"
    result = _run("--mode", "test")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    # Every path in output must exist; non-existent companions must not appear.
    for line in lines:
        assert (_REPO_ROOT / line).exists(), f"Non-existent companion leaked into output: {line!r}"


# ---------------------------------------------------------------------------
# Positive-path tests for _filter_by_mode (exercised directly to prove
# scoped file emission; no live session required).
# ---------------------------------------------------------------------------

_mod = _import_session_scope()
_filter_by_mode = _mod._filter_by_mode  # pylint: disable=protected-access
_fallback_worktree_status_files = _mod._fallback_worktree_status_files  # pylint: disable=protected-access


def test_filter_lint_mode_includes_python_source_files(tmp_path: Path) -> None:
    """lint mode returns Python source files that were touched."""
    (tmp_path / "teleclaude" / "foo" / "bar.py").parent.mkdir(parents=True)
    (tmp_path / "teleclaude" / "foo" / "bar.py").touch()
    (tmp_path / "teleclaude" / "foo" / "README.md").touch()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "script.sh").touch()
    touched = {"teleclaude/foo/bar.py", "teleclaude/foo/README.md", "tools/script.sh"}
    result = _filter_by_mode("lint", touched, tmp_path)
    assert "teleclaude/foo/bar.py" in result
    assert "teleclaude/foo/README.md" not in result
    assert "tools/script.sh" not in result


def test_filter_lint_mode_only_includes_touched_files(tmp_path: Path) -> None:
    """lint mode includes only files the session actually touched, no companions."""
    companion = tmp_path / "tests" / "unit" / "foo" / "test_bar.py"
    companion.parent.mkdir(parents=True)
    companion.touch()
    source = tmp_path / "teleclaude" / "foo" / "bar.py"
    source.parent.mkdir(parents=True)
    source.touch()
    touched = {"teleclaude/foo/bar.py"}
    result = _filter_by_mode("lint", touched, tmp_path)
    assert "teleclaude/foo/bar.py" in result
    assert "tests/unit/foo/test_bar.py" not in result


def test_filter_test_mode_maps_teleclaude_source_to_companion(tmp_path: Path) -> None:
    """test mode maps a teleclaude source file to its companion; source not included directly."""
    companion = tmp_path / "tests" / "unit" / "foo" / "test_bar.py"
    companion.parent.mkdir(parents=True)
    companion.touch()
    touched = {"teleclaude/foo/bar.py"}
    result = _filter_by_mode("test", touched, tmp_path)
    assert "tests/unit/foo/test_bar.py" in result
    assert "teleclaude/foo/bar.py" not in result


def test_filter_test_mode_includes_touched_test_file_directly(tmp_path: Path) -> None:
    """test mode includes a file already under tests/ without remapping."""
    test_file = tmp_path / "tests" / "unit" / "test_direct.py"
    test_file.parent.mkdir(parents=True)
    test_file.touch()
    touched = {"tests/unit/test_direct.py"}
    result = _filter_by_mode("test", touched, tmp_path)
    assert "tests/unit/test_direct.py" in result


def test_filter_test_mode_silently_skips_missing_companion(tmp_path: Path) -> None:
    """test mode emits an empty list when no companion exists for a source file."""
    touched = {"teleclaude/no_companion.py"}
    result = _filter_by_mode("test", touched, tmp_path)
    assert result == []


def test_fallback_worktree_status_files_returns_union_of_dirty_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback helper returns modified, untracked, deleted, and added paths from git status."""

    class _FakeGit:
        def status(self, *args: str) -> str:
            assert args == ("--porcelain",)
            return "\n".join(
                [
                    " M teleclaude/foo.py",
                    "?? tests/unit/test_bar.py",
                    " D docs/old.md",
                    "A  scripts/new.py",
                ]
            )

    class _FakeRepo:
        git = _FakeGit()

    monkeypatch.setattr(_mod, "Repo", lambda _project_root: _FakeRepo())

    result = _fallback_worktree_status_files(Path("/tmp/fake-repo"))

    assert result == {
        "teleclaude/foo.py",
        "tests/unit/test_bar.py",
        "docs/old.md",
        "scripts/new.py",
    }


def test_fallback_worktree_status_files_returns_empty_set_outside_git_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fallback helper returns an empty set when the project root is not a git repository."""

    def _raise_invalid_repo(_project_root: str) -> None:
        raise _mod.InvalidGitRepositoryError("not a repo")

    monkeypatch.setattr(_mod, "Repo", _raise_invalid_repo)

    assert _fallback_worktree_status_files(tmp_path) == set()


def test_main_routes_transcript_unavailable_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """TranscriptUnavailable routes through the fallback helper and still filters the result."""
    mod = _import_session_scope()
    touched_from_fallback = {"teleclaude/foo.py"}
    seen_mode: str | None = None
    seen_touched: set[str] | None = None
    seen_project_root: Path | None = None
    source = tmp_path / "teleclaude" / "foo.py"
    source.parent.mkdir(parents=True)
    source.touch()

    def _raise_transcript_unavailable(_project_root: str) -> set[str]:
        raise mod.TranscriptUnavailable("No transcript found for session")

    def _fake_filter(mode: str, touched: set[str], project_root: Path) -> list[str]:
        nonlocal seen_mode, seen_touched, seen_project_root
        seen_mode = mode
        seen_touched = touched
        seen_project_root = project_root
        return ["teleclaude/foo.py"]

    monkeypatch.setattr(sys, "argv", ["session_scope.py", "--mode", "lint", "--project-root", str(tmp_path)])
    monkeypatch.setattr(mod, "get_session_id", lambda: "fake-session-id")
    monkeypatch.setattr(mod, "_collect_session_touched_files", _raise_transcript_unavailable)
    monkeypatch.setattr(mod, "_fallback_worktree_status_files", lambda project_root: touched_from_fallback)
    monkeypatch.setattr(mod, "_filter_by_mode", _fake_filter)

    mod.main()

    assert seen_mode == "lint"
    assert seen_touched == touched_from_fallback
    assert seen_project_root == tmp_path
    assert capsys.readouterr().out == "teleclaude/foo.py\n"


def test_non_transcript_valueerror_collection_failure_exits_3(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ValueError that is not TranscriptUnavailable must still follow the exit-3 failure path."""
    mod = _import_session_scope()
    fallback_called = False

    def _raise_value_error(_project_root: str) -> set[str]:
        raise ValueError("db lookup failed")

    def _unexpected_fallback(_project_root: Path) -> set[str]:
        nonlocal fallback_called
        fallback_called = True
        return {"teleclaude/foo.py"}

    monkeypatch.setattr(sys, "argv", ["session_scope.py", "--mode", "lint"])
    monkeypatch.setattr(mod, "get_session_id", lambda: "fake-session-id")
    monkeypatch.setattr(mod, "_collect_session_touched_files", _raise_value_error)
    monkeypatch.setattr(mod, "_fallback_worktree_status_files", _unexpected_fallback)

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 3
    assert fallback_called is False
    assert "db lookup failed" in capsys.readouterr().err

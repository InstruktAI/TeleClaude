"""Expensive commit-boundary smoke tests for Rust pre-commit cargo gates."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMIT_MESSAGE = "chore(rust): smoke test"
CARGO_FMT_MARKER = "cargo-fmt"
CARGO_TEST_MARKER = "cargo-test"
GIT_BIN = "/usr/bin/git" if Path("/usr/bin/git").exists() else "git"

pytestmark = pytest.mark.expensive


@pytest.mark.timeout(90)
def test_tainted_rust_commit_is_blocked_by_cargo_hook(tmp_path: Path) -> None:
    """A failing cargo hook blocks telec code commit and leaves HEAD unchanged."""
    repo = _prepared_rust_repo(tmp_path)
    before = _git_stdout(repo, "rev-parse", "HEAD")

    _write_lib(repo, "pub fn answer()->u32{42}\n")
    _run_git(repo, "add", "crates/app/src/lib.rs")

    result = _telec_commit(repo)

    assert result.returncode != 0
    assert _git_stdout(repo, "rev-parse", "HEAD") == before
    assert _hook_marker(repo) == CARGO_FMT_MARKER


@pytest.mark.timeout(90)
def test_clean_rust_commit_lands_after_cargo_hooks_pass(tmp_path: Path) -> None:
    """A clean Rust change lands exactly one commit through telec code commit."""
    repo = _prepared_rust_repo(tmp_path)
    before = _git_stdout(repo, "rev-parse", "HEAD")

    _write_lib(
        repo,
        "pub fn answer() -> u32 {\n    42\n}\n\npub fn next_answer() -> u32 {\n    43\n}\n",
    )
    _run_git(repo, "add", "crates/app/src/lib.rs")

    result = _telec_commit(repo)

    assert result.returncode == 0
    after = _git_stdout(repo, "rev-parse", "HEAD")
    assert after != before
    assert _git_stdout(repo, "rev-parse", "HEAD^") == before
    assert _hook_marker(repo) == CARGO_TEST_MARKER


def _prepared_rust_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "rust-commit-fixture"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "teleclaude@example.invalid")
    _run_git(repo, "config", "user.name", "TeleClaude Test")
    _write_project_config(repo)
    _write_cargo_workspace(repo)
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "chore: seed")
    _run_git(repo, "switch", "-c", "rust-commit-smoke")
    _write_pre_commit_hook(repo)
    return repo


def _write_project_config(repo: Path) -> None:
    (repo / "teleclaude.yml").write_text("project_name: RustSmoke\nlanguages:\n  - rust\n", encoding="utf-8")


def _write_cargo_workspace(repo: Path) -> None:
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/app"]\n', encoding="utf-8")
    crate = repo / "crates" / "app"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        '[package]\nname = "app"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    _write_lib(repo, "pub fn answer() -> u32 {\n    42\n}\n")


def _write_lib(repo: Path, content: str) -> None:
    (repo / "crates" / "app" / "src" / "lib.rs").write_text(content, encoding="utf-8")


def _write_pre_commit_hook(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"printf '%s\\n' {CARGO_FMT_MARKER} > .git/rust-hook-marker\n"
        "cargo fmt --all -- --check\n"
        "printf '%s\\n' cargo-clippy > .git/rust-hook-marker\n"
        "cargo clippy --workspace --all-targets -- -D warnings\n"
        f"printf '%s\\n' {CARGO_TEST_MARKER} > .git/rust-hook-marker\n"
        "cargo test --workspace --lib --quiet\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


def _telec_commit(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TELEC_INVOCATION_CWD"] = str(repo)
    tmpdir = repo / ".telec-test-tmp"
    tmpdir.mkdir()
    env["TMPDIR"] = str(tmpdir)
    env["TMP"] = str(tmpdir)
    env["TEMP"] = str(tmpdir)
    return subprocess.run(
        [sys.executable, "-m", "teleclaude.cli.telec", "code", "commit", "-m", COMMIT_MESSAGE],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def _hook_marker(repo: Path) -> str:
    return (repo / ".git" / "rust-hook-marker").read_text(encoding="utf-8").strip()


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run([GIT_BIN, *args], cwd=repo)


def _git_stdout(repo: Path, *args: str) -> str:
    return _run_git(repo, *args).stdout.strip()


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)

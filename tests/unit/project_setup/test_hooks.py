"""Characterization tests for teleclaude.project_setup.hooks."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

import teleclaude.project_setup.hooks as hooks


def _has_exec_command(content: str) -> bool:
    """Check whether content contains `exec` as a shell command (not in comments)."""
    return bool(re.search(r"^\s+exec\s", content, re.MULTILINE))


def _make_precommit_entrypoint(extra: str = "", install_python: str = "/tmp/python") -> str:
    """Build a minimal pre-commit generated hook wrapper for testing."""
    return (
        "#!/usr/bin/env bash\n"
        f"INSTALL_PYTHON={install_python}\n"
        "ARGS=()\n"
        f"{extra}\n"
        'if [ -x "$INSTALL_PYTHON" ]; then\n'
        '  exec "$INSTALL_PYTHON" -mpre_commit "$@"\n'
        "fi\n"
    )


def _init_git_repo(repo: Path) -> None:
    """Initialize an isolated git repo with a local identity."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)


def _make_fake_precommit(
    bin_dir: Path,
    state_file: Path,
    *,
    first_action: str,
    first_rc: int,
    second_rc: int,
) -> Path:
    """Create a fake pre-commit that records invocations and simulates a given sequence.

    ``first_action`` runs on the first invocation (e.g. a shell snippet to modify files);
    subsequent invocations run no action and return ``second_rc``.
    """
    state_file.write_text("0", encoding="utf-8")
    stub = bin_dir / "pre-commit"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'n=$(cat "{state_file}")\n'
        "n=$((n+1))\n"
        f'echo "$n" > "{state_file}"\n'
        'if [ "$n" = "1" ]; then\n'
        f"  {first_action}\n"
        f"  exit {first_rc}\n"
        "fi\n"
        f"exit {second_rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _install_wrapper(repo: Path, install_python: str = "/does-not-exist") -> Path:
    """Install the TeleClaude pre-commit wrapper into the repo's git hooks dir."""
    hook_file = repo / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_text(_make_precommit_entrypoint(install_python=install_python), encoding="utf-8")
    hooks._ensure_precommit_entrypoint_guard(hook_file)
    hook_file.chmod(hook_file.stat().st_mode | 0o755)
    return hook_file


def _run_hook(hook_file: Path, repo: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(hook_file)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_install_precommit_hook_updates_framework_config_and_entrypoint_guard(tmp_path: Path) -> None:
    config_path = tmp_path / ".pre-commit-config.yaml"
    config_path.write_text(yaml.safe_dump({"repos": []}, sort_keys=False), encoding="utf-8")
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks.install_precommit_hook(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    local_repo = next(repo for repo in config["repos"] if repo["repo"] == "local")
    assert local_repo["hooks"][0]["id"] == hooks.DOCS_CHECK_MARKER
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content
    assert not _has_exec_command(content)


def test_add_raw_git_hook_is_idempotent_and_makes_file_executable(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    hooks._add_raw_git_hook(hooks_dir)
    hooks._add_raw_git_hook(hooks_dir)

    hook_file = hooks_dir / "pre-commit"
    content = hook_file.read_text(encoding="utf-8")
    assert content.count(hooks.STASH_PREVENTION_MARKER) == 1
    assert content.count(hooks.DOCS_CHECK_MARKER) == 1
    assert hook_file.stat().st_mode & 0o111


def test_ensure_precommit_entrypoint_guard_replaces_old_overlap_guard(tmp_path: Path) -> None:
    hook_file = tmp_path / "pre-commit"
    old_guard = f"# {hooks._OLD_OVERLAP_MARKER}\necho old guard\n"
    hook_file.write_text(
        _make_precommit_entrypoint(extra=old_guard),
        encoding="utf-8",
    )

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert hooks._OLD_OVERLAP_MARKER not in content
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content
    assert not _has_exec_command(content)


def test_ensure_precommit_entrypoint_guard_is_idempotent(tmp_path: Path) -> None:
    hook_file = tmp_path / "pre-commit"
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks._ensure_precommit_entrypoint_guard(hook_file)
    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert content.count(hooks.STASH_PREVENTION_MARKER) == 1
    assert content.count(hooks.RESTAGE_MARKER) == 1


def test_ensure_precommit_entrypoint_guard_replaces_existing_restage_block(tmp_path: Path) -> None:
    """When the installed wrapper has an outdated RESTAGE block, re-running must replace it."""
    hook_file = tmp_path / "pre-commit"
    outdated = (
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/tmp/python\n"
        "ARGS=()\n"
        f"# {hooks.STASH_PREVENTION_MARKER}: old stash guard\n"
        f"# {hooks.RESTAGE_MARKER}: outdated block\n"
        "echo outdated-restage-logic\n"
        "exit 1\n"
    )
    hook_file.write_text(outdated, encoding="utf-8")

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert "outdated-restage-logic" not in content
    assert content.count(hooks.RESTAGE_MARKER) == 1
    assert "_pre_staged=" in content


class TestRestageRuntimeBehavior:
    """End-to-end behavior of the generated pre-commit wrapper's restage block.

    These tests boot a temp git repo, install the wrapper, and run it against a
    fake pre-commit binary that simulates formatter modifications. They verify
    the 'complete in one go' contract from the fix(hooks) commit.
    """

    def test_restages_and_retries_when_formatter_modifies_staged_files(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        target = repo / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "invocations"
        _make_fake_precommit(
            bin_dir,
            state_file,
            first_action=f'printf "y = 2\\n" > "{repo}/a.py"',
            first_rc=1,
            second_rc=0,
        )

        hook_file = _install_wrapper(repo)
        result = _run_hook(hook_file, repo, bin_dir)

        assert result.returncode == 0, (
            f"wrapper should succeed after restage + retry; got rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert state_file.read_text(encoding="utf-8").strip() == "2", "pre-commit should run exactly twice"

        # Formatter's new content must be staged.
        staged = subprocess.run(
            ["git", "diff", "--cached", "a.py"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "y = 2" in staged

        # Working tree must be clean (no unstaged residue).
        unstaged = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert unstaged == ""

    def test_passes_through_on_clean_first_run(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "invocations"
        _make_fake_precommit(bin_dir, state_file, first_action=":", first_rc=0, second_rc=0)

        hook_file = _install_wrapper(repo)
        result = _run_hook(hook_file, repo, bin_dir)

        assert result.returncode == 0, result.stderr
        assert state_file.read_text(encoding="utf-8").strip() == "1", "pre-commit should run exactly once on clean path"

    def test_real_failure_without_modifications_is_not_retried(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "invocations"
        _make_fake_precommit(bin_dir, state_file, first_action=":", first_rc=1, second_rc=0)

        hook_file = _install_wrapper(repo)
        result = _run_hook(hook_file, repo, bin_dir)

        assert result.returncode == 1, "real pre-commit failures must propagate"
        assert state_file.read_text(encoding="utf-8").strip() == "1", "non-formatter failures must not trigger a retry"

    def test_retry_propagates_second_failure(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        target = repo / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "invocations"
        _make_fake_precommit(
            bin_dir,
            state_file,
            first_action=f'printf "y = 2\\n" > "{repo}/a.py"',
            first_rc=1,
            second_rc=2,
        )

        hook_file = _install_wrapper(repo)
        result = _run_hook(hook_file, repo, bin_dir)

        assert result.returncode == 2, "final rc must come from the retry run"
        assert state_file.read_text(encoding="utf-8").strip() == "2"

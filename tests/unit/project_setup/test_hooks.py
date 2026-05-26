"""Unit tests for teleclaude.project_setup.hooks — entrypoint safety guards."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import teleclaude.project_setup.hooks as hooks
from teleclaude.git import GIT_EXECUTABLE

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOME_PATHS_SCRIPT = _REPO_ROOT / "tools" / "lint" / "home_paths.py"


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


def test_ensure_precommit_safety_guards_replaces_old_overlap_guard(tmp_path: Path) -> None:
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True)
    old_guard = f"# {hooks._OLD_OVERLAP_MARKER}\necho old guard\n"
    hook_file.write_text(_make_precommit_entrypoint(extra=old_guard), encoding="utf-8")

    hooks.ensure_precommit_safety_guards(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    assert hooks._OLD_OVERLAP_MARKER not in content
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content


def test_ensure_precommit_safety_guards_is_idempotent(tmp_path: Path) -> None:
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True)
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks.ensure_precommit_safety_guards(tmp_path)
    hooks.ensure_precommit_safety_guards(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    assert content.count(hooks.STASH_PREVENTION_MARKER) == 1
    assert content.count(hooks.RESTAGE_MARKER) == 1


def test_ensure_precommit_safety_guards_replaces_existing_restage_block(tmp_path: Path) -> None:
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True)
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

    hooks.ensure_precommit_safety_guards(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    assert "outdated-restage-logic" not in content
    assert content.count(hooks.RESTAGE_MARKER) == 1


def test_ensure_precommit_safety_guards_restores_restage_retry_logic(tmp_path: Path) -> None:
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True)
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks.ensure_precommit_safety_guards(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    assert "_pre_staged" in content
    assert "_teleclaude_run_precommit" in content
    assert "git add -- $_modified" in content
    assert "Restaged formatter-modified files; re-running pre-commit..." in content
    assert 'exec "$INSTALL_PYTHON" -mpre_commit "${ARGS[@]}"' not in content


def test_ensure_precommit_safety_guards_cleans_up_legacy_staging_marker(tmp_path: Path) -> None:
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True)
    legacy = (
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/tmp/python\n"
        "ARGS=()\n"
        "# teleclaude-session-scoped-staging: legacy block\n"
        "echo legacy-staging\n"
    )
    hook_file.write_text(legacy, encoding="utf-8")

    hooks.ensure_precommit_safety_guards(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    assert "legacy-staging" not in content
    assert "teleclaude-session-scoped-staging" not in content
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content


def test_ensure_precommit_safety_guards_cleans_up_legacy_docs_check_marker(tmp_path: Path) -> None:
    """The pre-migration docs-check injection marker must be removed on re-run."""
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True)
    legacy = (
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/tmp/python\n"
        "ARGS=()\n"
        f"# {hooks._LEGACY_DOCS_CHECK_MARKER}: Reject hardcoded HOME paths\n"
        "echo legacy-docs-check\n"
    )
    hook_file.write_text(legacy, encoding="utf-8")

    hooks.ensure_precommit_safety_guards(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    assert "legacy-docs-check" not in content
    assert hooks._LEGACY_DOCS_CHECK_MARKER not in content


class TestEntrypointGuardBlockOrdering:
    """Verify the guard produces blocks in the correct sequence."""

    @pytest.mark.unit
    def test_blocks_appear_in_correct_order(self, tmp_path: Path) -> None:
        hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
        hook_file.parent.mkdir(parents=True)
        hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

        hooks.ensure_precommit_safety_guards(tmp_path)

        content = hook_file.read_text(encoding="utf-8")
        stash_pos = content.index(hooks.STASH_PREVENTION_MARKER)
        restage_pos = content.index(hooks.RESTAGE_MARKER)
        assert stash_pos < restage_pos


@pytest.mark.timeout(5)
class TestHomePathsScript:
    """Regression tests for tools/lint/home_paths.py — the HOME-path lint step.

    These execute the actual script against a real temp git repo to catch
    regressions like whitespace-splitting on filenames.
    """

    @staticmethod
    def _init_repo(tmp_path: Path) -> Path:
        subprocess.run([GIT_EXECUTABLE, "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run([GIT_EXECUTABLE, "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
        subprocess.run([GIT_EXECUTABLE, "config", "user.name", "Test"], cwd=tmp_path, check=True)
        return tmp_path

    @staticmethod
    def _run_check(repo: Path) -> int:
        result = subprocess.run(
            [sys.executable, str(_HOME_PATHS_SCRIPT), "--project-root", str(repo)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode

    def test_rejects_hardcoded_home_path_in_normal_filename(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        bad = repo / "normal.md"
        bad.write_text("see @/Users/anyone/.teleclaude/docs/index.yaml\n", encoding="utf-8")
        subprocess.run([GIT_EXECUTABLE, "add", "normal.md"], cwd=repo, check=True)

        assert self._run_check(repo) == 1

    def test_rejects_hardcoded_home_path_in_filename_with_space(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        bad = repo / "space name.md"
        bad.write_text("see @/Users/anyone/.teleclaude/docs/index.yaml\n", encoding="utf-8")
        subprocess.run([GIT_EXECUTABLE, "add", "space name.md"], cwd=repo, check=True)

        assert self._run_check(repo) == 1

    def test_accepts_clean_doc_with_filename_containing_space(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        ok = repo / "space name.md"
        ok.write_text("see `@~/.teleclaude/docs/index.yaml`\n", encoding="utf-8")
        subprocess.run([GIT_EXECUTABLE, "add", "space name.md"], cwd=repo, check=True)

        assert self._run_check(repo) == 0

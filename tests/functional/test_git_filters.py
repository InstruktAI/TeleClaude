"""Functional tests for teleclaude.project_setup.git_filters.

These exercise the real ``git`` binary (init/commit/checkout) and the real smudge
filter against a temp repo, so they live in the functional tier per the test
resource-discipline policy (rule 12: any test touching ``git`` is functional).
Subprocesses are synchronous (``subprocess.run(..., check=True)`` waits) and
``tmp_path`` auto-cleans, satisfying the zero-leak rule.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from teleclaude.git import GIT_EXECUTABLE, Repo
from teleclaude.project_setup import git_filters

pytestmark = pytest.mark.functional

# Fixture content carrying the portable token the smudge filter expands.
_STALE_DOC = "see @~/.teleclaude/docs/y.md\n"


def _init_docs_repo(tmp_path: Path, *, gitattributes: str, doc_relpath: str = "docs/x.md") -> Path:
    """Create a real git repo with a committed docs file holding the pre-smudge token.

    The filter driver is intentionally left unconfigured at commit time so the token
    is committed verbatim (undefined filter = pass-through), reproducing a checkout
    that was never smudged.
    """
    subprocess.run([GIT_EXECUTABLE, "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([GIT_EXECUTABLE, "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run([GIT_EXECUTABLE, "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run([GIT_EXECUTABLE, "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / ".gitattributes").write_text(gitattributes, encoding="utf-8")
    doc = tmp_path / doc_relpath
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(_STALE_DOC, encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([GIT_EXECUTABLE, "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


class TestForceResmudge:
    """Behavioral coverage of the working-tree re-smudge against a real git repo."""

    def test_restores_stale_filtered_docs_file(self, tmp_path: Path) -> None:
        repo_root = _init_docs_repo(tmp_path, gitattributes="docs/**/*.md filter=teleclaude-docs\n")
        repo = Repo(repo_root)
        git_filters._configure_filter_driver(repo)

        assert git_filters._force_resmudge(repo, repo_root) == 1

    def test_converges_to_zero_on_second_run(self, tmp_path: Path) -> None:
        # A second pass finding nothing proves the first pass actually expanded the
        # token (not merely re-checked-out an unchanged file).
        repo_root = _init_docs_repo(tmp_path, gitattributes="docs/**/*.md filter=teleclaude-docs\n")
        repo = Repo(repo_root)
        git_filters._configure_filter_driver(repo)
        git_filters._force_resmudge(repo, repo_root)

        assert git_filters._force_resmudge(repo, repo_root) == 0

    def test_skips_locally_modified_file(self, tmp_path: Path) -> None:
        repo_root = _init_docs_repo(tmp_path, gitattributes="docs/**/*.md filter=teleclaude-docs\n")
        repo = Repo(repo_root)
        git_filters._configure_filter_driver(repo)
        (repo_root / "docs/x.md").write_text(_STALE_DOC + "uncommitted edit\n", encoding="utf-8")

        assert git_filters._force_resmudge(repo, repo_root) == 0

    def test_respects_filter_disabled_override(self, tmp_path: Path) -> None:
        # docs/** is filtered, but a nested -filter override must be honoured so the
        # token-bearing file is left untouched (and the scan converges).
        repo_root = _init_docs_repo(
            tmp_path,
            gitattributes="docs/**/*.md filter=teleclaude-docs\ndocs/keep/**/*.md -filter\n",
            doc_relpath="docs/keep/z.md",
        )
        repo = Repo(repo_root)
        git_filters._configure_filter_driver(repo)

        assert git_filters._force_resmudge(repo, repo_root) == 0


class TestEnsureGitFilters:
    """Behavioral coverage of the self-healing entry point."""

    def test_configures_driver_and_heals_stale_docs(self, tmp_path: Path) -> None:
        # If ensure both configured the driver and re-smudged, a follow-up scan finds
        # nothing stale. A non-zero result would mean the driver was never installed.
        repo_root = _init_docs_repo(tmp_path, gitattributes="docs/**/*.md filter=teleclaude-docs\n")

        git_filters.ensure_git_filters(repo_root)

        assert git_filters._force_resmudge(Repo(repo_root), repo_root) == 0

    def test_skips_when_not_a_git_repository(self, tmp_path: Path) -> None:
        # No .git present: the guard must short-circuit before constructing a Repo
        # (which would raise). Completing without error is the contract.
        git_filters.ensure_git_filters(tmp_path)

        assert not (tmp_path / ".git").exists()

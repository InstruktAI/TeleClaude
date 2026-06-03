"""Characterization tests for teleclaude.project_setup.git_filters."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.git import GIT_EXECUTABLE, Repo
from teleclaude.project_setup import git_filters

pytestmark = pytest.mark.unit

# Fixture content carrying the portable token the smudge filter expands.
_STALE_DOC = "see @~/.teleclaude/docs/y.md\n"


def test_setup_git_filters_skips_when_git_directory_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Print a clear message when filter setup runs outside a git repo."""
    git_filters.setup_git_filters(tmp_path)

    assert "not a git repository" in capsys.readouterr().out


def test_setup_git_filters_configures_expected_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Install the @-scoped clean/smudge filters without rewriting docs."""
    (tmp_path / ".git").mkdir()
    calls: list[tuple[object, str, str]] = []

    def _fake_config(repo: object, key: str, value: str) -> None:
        calls.append((repo, key, value))

    monkeypatch.setattr(git_filters, "_run_git_config", _fake_config)

    mock_repo = MagicMock()
    with patch("teleclaude.project_setup.git_filters.Repo", return_value=mock_repo):
        git_filters.setup_git_filters(tmp_path)

    home = str(Path.home())
    assert calls == [
        (mock_repo, "filter.teleclaude-docs.smudge", f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'),
        (mock_repo, "filter.teleclaude-docs.clean", f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'),
        (mock_repo, "filter.teleclaude-docs.required", "true"),
    ]
    assert "configured smudge/clean filters" in capsys.readouterr().out


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

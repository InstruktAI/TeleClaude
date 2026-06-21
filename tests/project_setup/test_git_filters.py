"""Functional coverage for the docs-filter self-heal in ``ensure_git_filters``.

Exercises the self-heal against a real git repo and the anchored filter driver:
the residue lane that converges a tree last smudged under the historical bare
pattern, the genuine-edit guard that protects real edits, and the untouched
anchored-token lane.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from teleclaude.git import GIT_EXECUTABLE
from teleclaude.project_setup.git_filters import ensure_git_filters

_SPEC = "general/spec/tools/telec-cli"
_HOME = str(Path.home())
_DOC = "docs/spec/teleclaude-config.md"


def _git(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT_EXECUTABLE, *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_repo(project_root: Path, committed_body: str) -> None:
    """Init a repo with the docs filter attribute and one committed doc.

    The doc is committed in its portable (cleaned) form before the filter driver
    is installed, so git stores the body verbatim — the committed contract the
    self-heal must converge the working tree back to.
    """
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test")
    (project_root / ".gitattributes").write_text("docs/**/*.md filter=teleclaude-docs\n", encoding="utf-8")
    doc = project_root / _DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(committed_body, encoding="utf-8")
    _git(project_root, "add", "-A")
    _git(project_root, "commit", "-m", "seed")


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_residue_reconciled_to_committed_form(tmp_path: Path) -> None:
    """A bare-absolute home path left by a prior filter pattern is reset to source."""
    committed = "See `~/.teleclaude/teleclaude.yml` for config.\n"
    _init_repo(tmp_path, committed)
    ensure_git_filters(tmp_path)  # install the anchored driver; tree already consistent
    assert not _git(tmp_path, "status", "--porcelain").strip()

    # A tree last smudged under the historical bare driver carries the portable
    # token expanded to a bare-absolute home path the anchored clean cannot contract.
    residue = committed.replace("~/.teleclaude", f"{_HOME}/.teleclaude")
    (tmp_path / _DOC).write_text(residue, encoding="utf-8")
    assert _git(tmp_path, "status", "--porcelain").strip()

    ensure_git_filters(tmp_path)

    assert (tmp_path / _DOC).read_text(encoding="utf-8") == committed
    assert not _git(tmp_path, "status", "--porcelain").strip()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_genuine_edit_preserved(tmp_path: Path) -> None:
    """A real content edit that also carries the home-path form is left untouched."""
    committed = "See `~/.teleclaude/teleclaude.yml` for config.\n"
    _init_repo(tmp_path, committed)
    ensure_git_filters(tmp_path)

    edited = f"See `{_HOME}/.teleclaude/teleclaude.yml` for config.\nA real new prose line.\n"
    (tmp_path / _DOC).write_text(edited, encoding="utf-8")

    ensure_git_filters(tmp_path)

    assert (tmp_path / _DOC).read_text(encoding="utf-8") == edited
    assert _git(tmp_path, "status", "--porcelain").strip()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_anchored_token_lane_resmudges(tmp_path: Path) -> None:
    """The portable token on disk (fresh clone) is still expanded by the self-heal."""
    committed = "Ref @~/.teleclaude/docs/x.md here.\n"
    _init_repo(tmp_path, committed)
    assert (tmp_path / _DOC).read_text(encoding="utf-8") == committed

    ensure_git_filters(tmp_path)

    expected = committed.replace("@~/.teleclaude", f"@{_HOME}/.teleclaude")
    assert (tmp_path / _DOC).read_text(encoding="utf-8") == expected
    assert not _git(tmp_path, "status", "--porcelain").strip()

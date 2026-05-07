"""Tests for git-based scoping primitives."""

from __future__ import annotations

from pathlib import Path

from teleclaude.git import Repo
from teleclaude.session_scoping._git import paths_changed_since, read_head_sha


def _init_repo(workspace: Path) -> Repo:
    repo = Repo.init(str(workspace))
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test")
    repo.git.config("commit.gpgsign", "false")
    return repo


def _commit(repo: Repo, name: str, body: str = "x", message: str = "msg") -> str:
    workspace = Path(str(repo.working_tree_dir))
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    repo.git.add(name)
    repo.git.commit("-m", message)
    return repo.git.rev_parse("HEAD").strip()


def test_read_head_sha_returns_current_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    sha = _commit(repo, "first.txt")

    assert read_head_sha(str(tmp_path)) == sha


def test_read_head_sha_returns_none_for_non_git_path(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert read_head_sha(str(plain)) is None


def test_paths_changed_since_captures_uncommitted_edits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    anchor = _commit(repo, "stable.txt")

    (tmp_path / "dirty.txt").write_text("new")
    repo.git.add("dirty.txt")

    paths = paths_changed_since(str(tmp_path), anchor)
    assert "dirty.txt" in paths


def test_paths_changed_since_captures_in_turn_commits(tmp_path: Path) -> None:
    """Same-turn commit case: file edited and committed after the anchor.

    The previous logic relied on `git diff HEAD` (dirty state) and lost
    these paths once the commit landed. The anchor-based diff captures
    them because the comparison is against the SHA at turn-start, not HEAD.
    """
    repo = _init_repo(tmp_path)
    anchor = _commit(repo, "stable.txt")
    _commit(repo, "feature.py", body="def f(): pass", message="add feature")

    paths = paths_changed_since(str(tmp_path), anchor)
    assert "feature.py" in paths


def test_paths_changed_since_captures_committed_and_dirty_together(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    anchor = _commit(repo, "stable.txt")
    _commit(repo, "committed.py", message="commit one")
    (tmp_path / "still_dirty.txt").write_text("pending")

    paths = paths_changed_since(str(tmp_path), anchor)
    assert "committed.py" in paths
    assert "still_dirty.txt" in paths


def test_paths_changed_since_returns_empty_set_on_invalid_anchor(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, "first.txt")

    paths = paths_changed_since(str(tmp_path), "not-a-real-sha")
    assert paths == set()

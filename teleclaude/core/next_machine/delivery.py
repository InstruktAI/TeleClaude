"""Delivery management — move work items from roadmap to delivered.yaml and clean up.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import yaml
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import DeliveredDict, DeliveredEntry, RoadmapEntry
from teleclaude.core.next_machine.icebox import clean_dependency_references
from teleclaude.core.next_machine.roadmap import load_roadmap, save_roadmap
from teleclaude.core.next_machine.state_io import read_text_sync, write_text_sync

logger = get_logger(__name__)


def _delivered_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / "delivered.yaml"


def load_delivered(cwd: str) -> list[DeliveredEntry]:
    """Parse todos/delivered.yaml and return ordered list of entries."""
    path = _delivered_path(cwd)
    if not path.exists():
        return []

    content = read_text_sync(path)
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return []

    entries: list[DeliveredEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        children_raw = item.get("children")
        children = list(children_raw) if isinstance(children_raw, list) else None
        entries.append(
            DeliveredEntry(
                slug=item["slug"],
                date=str(item.get("date", "")),
                commit=item.get("commit"),
                children=children,
            )
        )
    return entries


def load_delivered_slugs(cwd: str) -> set[str]:
    """Return set of delivered slugs for fast lookup."""
    return {e.slug for e in load_delivered(cwd)}


def save_delivered(cwd: str, entries: list[DeliveredEntry]) -> None:
    """Write entries back to todos/delivered.yaml."""
    path = _delivered_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[DeliveredDict] = []
    for entry in entries:
        item: DeliveredDict = {"slug": entry.slug, "date": entry.date}
        if entry.commit:
            item["commit"] = entry.commit
        if entry.children:
            item["children"] = entry.children
        data.append(item)

    header = "# Delivered work items. Newest first.\n\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)


def deliver_to_delivered(
    cwd: str,
    slug: str,
    *,
    commit: str | None = None,
) -> bool:
    """Move a slug from roadmap to delivered (prepended). Returns False only if slug is unknown.

    Idempotent: returns True if the slug is already in delivered.yaml.
    If no commit SHA is provided, auto-detects HEAD of the repository.
    """
    entries = load_roadmap(cwd)
    entry = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            entry = entries.pop(i)
            break
    if entry is None:
        # Not in roadmap — check if already delivered (idempotent success)
        if slug in load_delivered_slugs(cwd):
            return True
        # Bugs intentionally skip the roadmap; accept any slug with a todo directory
        if not (Path(cwd) / "todos" / slug).exists():
            return False
    else:
        save_roadmap(cwd, entries)

    if commit is None:
        try:
            repo = Repo(cwd, search_parent_directories=True)
            commit = repo.head.commit.hexsha[:12]
        except (InvalidGitRepositoryError, NoSuchPathError, ValueError):
            pass

    delivered = load_delivered(cwd)
    delivered.insert(
        0,
        DeliveredEntry(
            slug=slug,
            date=date.today().isoformat(),
            commit=commit,
        ),
    )
    save_delivered(cwd, delivered)
    return True


def reconcile_roadmap_after_merge(cwd: str) -> list[str]:
    """Remove stale entries from roadmap that squash merges may re-introduce.

    Two cases:
    1. Ghost entries: slug exists in both roadmap and delivered.yaml
    2. Orphan entries: slug in roadmap with no todo directory and not delivered

    Returns list of removed slugs for logging.
    """
    entries = load_roadmap(cwd)
    delivered_slugs = load_delivered_slugs(cwd)
    todos_dir = Path(cwd) / "todos"

    keep: list[RoadmapEntry] = []
    removed: list[str] = []

    for entry in entries:
        is_ghost = entry.slug in delivered_slugs
        is_orphan = not (todos_dir / entry.slug).exists() and entry.slug not in delivered_slugs
        if is_ghost or is_orphan:
            removed.append(entry.slug)
            clean_dependency_references(cwd, entry.slug)
        else:
            keep.append(entry)

    if removed:
        save_roadmap(cwd, keep)

    return removed


def _run_git_cmd(
    args: list[str], *, cwd: str, timeout: float = 30
) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out after %.0fs", " ".join(args[:2]), timeout)
        return 1, "", f"timeout after {timeout}s"


def cleanup_delivered_slug(
    cwd: str,
    slug: str,
    *,
    branch: str | None = None,
    remove_remote_branch: bool = True,
) -> None:
    """Idempotent cleanup of all physical artifacts for a delivered slug.

    Each step is a no-op if the artifact is already gone.

    Args:
        cwd: Project root directory.
        slug: Work item slug.
        branch: Git branch name (defaults to slug).
        remove_remote_branch: Whether to delete the remote tracking branch.
    """
    branch = branch or slug

    # 1. Remove worktree
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if worktree_path.exists():
        rc, _, stderr = _run_git_cmd(["worktree", "remove", "--force", str(worktree_path)], cwd=cwd, timeout=10)
        if rc != 0:
            logger.warning("worktree remove failed for %s: %s", slug, stderr.strip())

    # 2. Delete local branch
    _run_git_cmd(["branch", "-D", branch], cwd=cwd)

    # 3. Delete remote branch (non-fatal, tight timeout)
    if remove_remote_branch:
        _run_git_cmd(["push", "origin", "--delete", branch], cwd=cwd, timeout=5)

    # 4. Remove todo directory
    todo_dir = Path(cwd) / "todos" / slug
    if todo_dir.exists():
        shutil.rmtree(str(todo_dir), ignore_errors=True)

    # 5. Clean dependency references
    clean_dependency_references(cwd, slug)


def sweep_completed_groups(cwd: str) -> list[str]:
    """Auto-deliver group parents whose children are all delivered.

    A group parent is any todo with a non-empty breakdown.todos list.
    When every child slug appears in delivered.yaml, the parent is
    delivered and its todo directory removed.

    Returns list of swept group slugs.
    """
    todos_dir = Path(cwd) / "todos"
    if not todos_dir.is_dir():
        return []

    delivered_slugs = load_delivered_slugs(cwd)
    swept: list[str] = []

    for entry in sorted(todos_dir.iterdir()):
        if not entry.is_dir():
            continue
        state_path = entry / "state.yaml"
        # Backward compat: fall back to state.json
        if not state_path.exists():
            legacy_path = entry / "state.json"
            if legacy_path.exists():
                state_path = legacy_path
        if not state_path.exists():
            continue

        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue

        breakdown = state.get("breakdown")
        if not isinstance(breakdown, dict):
            continue
        children = breakdown.get("todos")
        if not isinstance(children, list) or not children:
            continue

        # Check if ALL children have been delivered
        if not all(child in delivered_slugs for child in children):
            continue

        group_slug = entry.name

        delivered = deliver_to_delivered(cwd, group_slug)

        if delivered:
            # deliver_to_delivered added entry without children — patch it in
            entries = load_delivered(cwd)
            for d_entry in entries:
                if d_entry.slug == group_slug and d_entry.children is None:
                    d_entry.children = list(children)
                    break
            save_delivered(cwd, entries)
        else:
            # Not in roadmap — add directly to delivered.yaml with children
            try:
                repo = Repo(cwd, search_parent_directories=True)
                head_sha: str | None = repo.head.commit.hexsha[:12]
            except (InvalidGitRepositoryError, NoSuchPathError, ValueError):
                head_sha = None
            entries = load_delivered(cwd)
            entries.insert(
                0,
                DeliveredEntry(
                    slug=group_slug,
                    date=date.today().isoformat(),
                    commit=head_sha,
                    children=list(children),
                ),
            )
            save_delivered(cwd, entries)

        # Clean up physical artifacts (worktree/branch no-op for group parents)
        cleanup_delivered_slug(cwd, group_slug, remove_remote_branch=False)
        swept.append(group_slug)
        logger.info("Group sweep: delivered %s (all %d children complete)", group_slug, len(children))

    return swept

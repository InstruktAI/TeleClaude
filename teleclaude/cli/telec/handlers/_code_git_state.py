"""Working-tree and index inspection for the ``telec code`` commit path.

Read-only git state queries: what is untracked, staged, unstaged, unmerged, or
partially staged, and which branch is checked out. Kept apart from the command
handlers so the commit path reads as policy and these read as observation.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from teleclaude.git import Repo


def get_untracked_files(project_root: Path) -> list[str]:
    """Return list of files git doesn't know about yet (modulo .gitignore).

    These are the only paths in a pathspec that genuinely require staging
    before commit — git refuses ``git commit -- newfile`` otherwise. Modified
    tracked files are committed straight from the working tree by pathspec
    and need no staging at all.
    """
    repo = Repo(str(project_root))
    output: str = repo.git.ls_files("--others", "--exclude-standard")
    return [f.strip() for f in output.strip().splitlines() if f.strip()]


def _get_staged_files(project_root: Path, *, include_deletions: bool = False) -> list[str]:  # pyright: ignore[reportUnusedFunction]
    """Return list of staged file paths (those currently in the index).

    Used to distinguish "agent explicitly staged this via `telec code add`"
    from "untouched-untracked, drop from pathspec." Not currently called
    from the commit hot path (replaced by ``working_tree_snapshot``);
    retained for test suites and external callers.
    """
    repo = Repo(str(project_root))
    diff_filter = "ACMRD" if include_deletions else "ACMR"
    output: str = repo.git.diff("--cached", "--name-only", f"--diff-filter={diff_filter}")
    return [f.strip() for f in output.strip().splitlines() if f.strip()]


def get_unmerged_files(project_root: Path) -> list[str]:
    """Return paths in unmerged-index state (post-conflict, pre-resolution-stage).

    `git ls-files -u` emits one row per conflict stage (1=base, 2=ours,
    3=theirs); dedupe by path. These paths must be `git add`-ed after
    manual conflict resolution so git can complete the commit — the seal
    routes that through `_stage_files` internally.
    """
    repo = Repo(str(project_root))
    output: str = repo.git.ls_files("-u")
    paths: set[str] = set()
    for line in output.splitlines():
        # Format: "<mode> <hash> <stage>\t<path>"
        tab = line.find("\t")
        if tab >= 0:
            paths.add(line[tab + 1 :].strip())
    return sorted(paths)


def dirty_paths(project_root: Path) -> set[str]:
    """Return paths with any pending change — staged, unstaged, or untracked.

    Used to validate ``--include`` declarations: a declared path must
    contribute *some* change to the commit.
    """
    repo = Repo(str(project_root))
    parts: set[str] = set()
    # Staged (incl. deletions) and unstaged tracked changes.
    parts.update(
        f.strip() for f in repo.git.diff("--cached", "--name-only", "--diff-filter=ACMRD").splitlines() if f.strip()
    )
    parts.update(f.strip() for f in repo.git.diff("--name-only", "--diff-filter=ACMRD").splitlines() if f.strip())
    # Untracked files and unmerged-index files (post-conflict).
    parts.update(get_untracked_files(project_root))
    parts.update(get_unmerged_files(project_root))
    return parts


@dataclass(frozen=True)
class WorkingTreeSnapshot:
    """Single-shot view of the working tree + index.

    Replaces five separate gitpython calls in the commit hot path
    (`ls-files --others`, two `diff --cached`, `ls-files -u`, `diff
    --name-only`). One `git status --porcelain=v1 -uall -z` produces
    everything the commit path needs to decide pathspec, staging, and
    partial-staging guard. Single call → shorter window between flock
    acquisition and the actual commit → fewer chances for the Python
    parent to die mid-sequence and orphan .git/index.lock.
    """

    untracked: frozenset[str] = field(default_factory=frozenset)
    staged: frozenset[str] = field(default_factory=frozenset)
    modified_unstaged: frozenset[str] = field(default_factory=frozenset)
    partial_staged: frozenset[str] = field(default_factory=frozenset)
    unmerged: frozenset[str] = field(default_factory=frozenset)

    @property
    def dirty(self) -> frozenset[str]:
        """Any pending change — staged, unstaged, untracked, or unmerged."""
        return self.untracked | self.staged | self.modified_unstaged | self.unmerged


_UNMERGED_CODES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})


def working_tree_snapshot(project_root: Path) -> WorkingTreeSnapshot:
    """Capture the working tree + index state in one git invocation.

    `git status --porcelain=v1 -uall -z` is read-only on the index (no
    `.git/index.lock` taken) and produces every status bit the commit
    path needs. Format: each entry is `XY<space><path>\\0`, where X is
    the index status and Y is the worktree status. Rename/copy entries
    consume two NUL-separated tokens (`R  newpath\\0oldpath\\0`); the
    parser skips the old-path token.
    """
    repo = Repo(str(project_root))
    raw: str = repo.git.status("--porcelain=v1", "-uall", "-z")
    tokens = raw.split("\x00")
    untracked: set[str] = set()
    staged: set[str] = set()
    modified_unstaged: set[str] = set()
    partial_staged: set[str] = set()
    unmerged: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token or len(token) < 3:
            continue
        xy = token[:2]
        path = token[3:]
        # Rename/copy consumes the next token (old path) — skip it.
        if xy[0] in ("R", "C"):
            i += 1
        if xy == "??":
            untracked.add(path)
        elif xy == "!!":
            continue  # ignored
        elif xy in _UNMERGED_CODES:
            unmerged.add(path)
        else:
            if xy[0] != " ":
                staged.add(path)
            if xy[1] != " ":
                modified_unstaged.add(path)
                if xy[0] != " ":
                    partial_staged.add(path)
    return WorkingTreeSnapshot(
        untracked=frozenset(untracked),
        staged=frozenset(staged),
        modified_unstaged=frozenset(modified_unstaged),
        partial_staged=frozenset(partial_staged),
        unmerged=frozenset(unmerged),
    )


def _check_partial_staging(project_root: Path, *, pathspec: list[str]) -> None:  # pyright: ignore[reportUnusedFunction]
    """Block commits when a file in our pathspec is partially staged.

    `git commit -- <path>` records the working-tree version of <path>, not
    just the staged hunks. So if a file is partially staged (staged hunks +
    later working-tree edit), the commit captures BOTH — silently sweeping
    in unstaged content the agent never declared. Foreign partial-staging
    (outside our pathspec) is not our concern.

    Not currently called from the commit hot path (the guard is inlined
    against ``working_tree_snapshot``); retained for test suites and
    external callers.
    """
    repo = Repo(str(project_root))
    staged = set(repo.git.diff("--cached", "--name-only").strip().splitlines())
    unstaged = set(repo.git.diff("--name-only").strip().splitlines())
    overlap = (staged & unstaged) & set(pathspec)
    if not overlap:
        return
    print("ERROR: partially staged files in commit pathspec:", file=sys.stderr)
    for f in sorted(overlap):
        print(f"  {f}", file=sys.stderr)
    print(
        "\n`git commit -- <path>` would commit the working-tree version, sweeping\n"
        "in unstaged hunks you did not declare. Fully (re)stage each file via the\n"
        "sealed recovery path (`telec code add` accepts partial-staged tracked\n"
        "files for exactly this case), then re-run telec code commit:\n"
        "  telec code add " + " ".join(sorted(overlap)),
        file=sys.stderr,
    )
    raise SystemExit(1)


def resolve_current_branch(project_root: Path) -> str:
    """Return the current git branch name."""
    repo = Repo(str(project_root))
    branch: str = repo.git.rev_parse("--abbrev-ref", "HEAD")
    return branch.strip()

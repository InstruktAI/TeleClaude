"""Converge a repository to the documentation layout the context domain reads.

The layout is local documentation under ``docs/local``, local agent artifacts
under ``agents/local``, and snippet references in the qualified identity form
(``projects/<slug>/…``, ``people/<slug>/…``, ``companies/<slug>/…``). This module
is the migration boundary: it is the one place that names the retired layout,
because its job is to read it as input.

``rewrite_layout_text`` is the pure identifier-level rewrite shared by every
caller. ``rewrite_layout_references`` applies it to a checkout's text files,
and ``converge_root`` moves one repository and commits it through an injected
committer, restoring only its own changes when that commit is refused.
The contract is ``projects/teleclaude/spec/feature/context/documentation-layout-convergence``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.git import GitCommandError, Repo
from teleclaude.snippet_validation import UndeclaredProjectSlugError, read_declared_project_slug

logger = get_logger(__name__)

_DOCS_DIR: Final = "docs"
_AGENTS_DIR: Final = "agents"
_RETIRED_HALF: Final = "project"
_LOCAL_HALF: Final = "local"
_PUBLISHED_HALF: Final = "global"
_RETIRED_DOCS: Final = PurePosixPath(_DOCS_DIR, _RETIRED_HALF)
_RETIRED_AGENTS: Final = PurePosixPath(_AGENTS_DIR, _RETIRED_HALF)
#: Each retired directory and the directory it becomes.
LAYOUT_MOVES: Final[tuple[tuple[PurePosixPath, PurePosixPath], ...]] = (
    (_RETIRED_DOCS, PurePosixPath(_DOCS_DIR, _LOCAL_HALF)),
    (_RETIRED_AGENTS, PurePosixPath(_AGENTS_DIR, _LOCAL_HALF)),
)
_PUBLISHED_DOCS_PREFIX: Final = f"{_DOCS_DIR}/{_PUBLISHED_HALF}/"

_TAXONOMY_ALTERNATION: Final = "|".join(sorted(TAXONOMY_TYPES))
_RETIRED_DOCS_PATTERN: Final = re.compile(r"(?<![\w.-])docs/project(?=/|\b)")
_RETIRED_AGENTS_PATTERN: Final = re.compile(r"(?<![\w.-])agents/project(?=/|\b)")
_LOCAL_DOCS_REPLACEMENT: Final = "docs/local"
_LOCAL_AGENTS_REPLACEMENT: Final = "agents/local"
_UNQUALIFIED_PROJECT_PATTERN: Final = re.compile(rf"(?<![\w./-])project/({_TAXONOMY_ALTERNATION})/")
_PROJECT_IDENTITY_TEMPLATE: Final = "projects/{slug}/{taxonomy}/"
_SINGULAR_TIER_PATTERN: Final = re.compile(rf"(?<![\w./-])(person|company)/([a-z0-9-]+)/({_TAXONOMY_ALTERNATION})/")
_TIER_PREFIX_BY_SINGULAR: Final[dict[str, str]] = {"person": "people", "company": "companies"}
_TIER_IDENTITY_TEMPLATE: Final = "{prefix}/{owner}/{taxonomy}/"
_REGISTERED_SLUG_PATTERN_TEMPLATE: Final = r"(?<![\w./-])({slugs})/({taxonomies})/"
_MARKDOWN_SUFFIX: Final = ".md"
_UTF8: Final = "utf-8"
_NUL_BYTE: Final = b"\0"

_ADR_DIRNAME: Final = "adr"
_H2_PREFIX: Final = "## "
_SEE_ALSO_HEADING: Final = "## See Also"
_CHANGELOG_GLOB: Final = "CHANGELOG*"
_GENERATED_BASENAMES: Final[frozenset[str]] = frozenset({"AGENTS.md", "CLAUDE.md", "index.yaml"})
#: Files a pull leaves behind in a retired directory that git no longer tracks:
#: the generated catalog and operating-system folder metadata. A retired
#: directory holding only these, beside its converged counterpart, is residue.
_RESIDUE_BASENAMES: Final[frozenset[str]] = frozenset({"index.yaml", ".DS_Store"})
#: Files whose job is to name the retired layout as input; never rewritten.
MIGRATION_BOUNDARY_GLOBS: Final[tuple[str, ...]] = (
    "teleclaude/docs_layout.py",
    "teleclaude/core/todos_db/_docs_local_rename.py",
    "docs/*/spec/feature/context/documentation-layout-convergence.md",
)

_LS_FILES_ARGS: Final = ("-z", "--cached", "--others", "--exclude-standard")
_LS_FILES_TRACKED_ARGS: Final = ("-z", "--cached")
_LS_FILES_STAGE_ARGS: Final = ("-s", "-z")
_STATUS_ARGS: Final = ("--porcelain=v1", "-z", "--untracked-files=all")
_STATUS_UNTRACKED: Final = "??"
_STATUS_RENAME_CODES: Final = frozenset({"R", "C"})
_PATHSPEC_SEPARATOR: Final = "--"
_RESET_ARGS: Final = ("-q",)
_DIFF_TREE_ARGS: Final = ("--no-commit-id", "--name-only", "-r", "--no-renames", "-z")
_LS_TREE_ARGS: Final = ("--name-only",)
_WORKTREE_LIST_ARGS: Final = ("list", "--porcelain")
_WORKTREE_LINE_PREFIX: Final = "worktree "
_MENTION_TEMPLATE: Final = "{path}:{line}"

_LOG_ROOT_EVENT: Final = "docs_layout_convergence_root"
_LOG_EFFECT_FAILED_EVENT: Final = "docs_layout_convergence_effect_failed"
_HEAD_REF: Final = "HEAD"
_LS_TREE_RECURSIVE_ARGS: Final = ("-r", "--name-only", "-z")


class LayoutConvergenceOutcome(StrEnum):
    """Closed per-root result vocabulary for documentation layout convergence."""

    CURRENT = "current"
    MIGRATED_COMMITTED = "migrated_committed"
    MIGRATED_UNTRACKED = "migrated_untracked"
    PULL_REQUIRED = "pull_required"
    BLOCKED_BOTH_LAYOUTS = "blocked_both_layouts"
    BLOCKED_UNDECLARED_SLUG = "blocked_undeclared_slug"
    BLOCKED_DIRTY = "blocked_dirty"
    RESTORED_AFTER_REFUSED_COMMIT = "restored_after_refused_commit"
    RESTORE_CONFLICT = "restore_conflict"
    BLOCKED_INCOMPLETE = "blocked_incomplete"
    DEFERRED_NO_IDENTITY = "deferred_no_identity"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


#: Outcomes that make a convergence run exit non-zero.
FAILING_OUTCOMES: Final[frozenset[LayoutConvergenceOutcome]] = frozenset(
    {
        LayoutConvergenceOutcome.BLOCKED_BOTH_LAYOUTS,
        LayoutConvergenceOutcome.BLOCKED_UNDECLARED_SLUG,
        LayoutConvergenceOutcome.BLOCKED_DIRTY,
        LayoutConvergenceOutcome.RESTORED_AFTER_REFUSED_COMMIT,
        LayoutConvergenceOutcome.RESTORE_CONFLICT,
        LayoutConvergenceOutcome.BLOCKED_INCOMPLETE,
        LayoutConvergenceOutcome.DEFERRED_NO_IDENTITY,
        LayoutConvergenceOutcome.FAILED,
    }
)


class PublishedIdentityPolicy(StrEnum):
    """How identity rules treat a repository's published half (``docs/global``)."""

    REWRITE = "rewrite"
    REPORT = "report"


class LayoutCommitRefused(RuntimeError):
    """The injected committer did not land the convergence commit."""


Committer = Callable[[Path, Sequence[str]], None]
Fetcher = Callable[[Repo], bool]


@dataclass(frozen=True)
class LayoutRewriteResult:
    """Paths a reference rewrite changed, and published-half mentions it left for the owner."""

    changed_paths: tuple[str, ...]
    published_mentions: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayoutConvergenceResult:
    """One root's convergence outcome and the paths it concerns."""

    root: Path
    outcome: LayoutConvergenceOutcome
    touched_paths: tuple[str, ...] = ()
    blocking_paths: tuple[str, ...] = ()
    published_mentions: tuple[str, ...] = ()
    worktrees: tuple[str, ...] = ()
    commit: str | None = None
    removed_residue: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RewritePlan:
    """Planned rewrites keyed by checkout-relative path: (bytes read, bytes to write)."""

    rewrites: dict[str, tuple[bytes, bytes]] = field(default_factory=dict)
    published_mentions: tuple[str, ...] = ()


@dataclass(frozen=True)
class _MovedFile:
    """One file a move relocates: where it came from and the bytes it had before the run."""

    retired_path: str
    digest: str


@dataclass(frozen=True)
class _MovePlan:
    """What one convergence would move and rewrite, before anything is written."""

    moves: tuple[tuple[PurePosixPath, PurePosixPath], ...]
    tracked_moved: tuple[str, ...]
    rewrite_plan: _RewritePlan


def _registered_slug_pattern(registered_slugs: Iterable[str]) -> re.Pattern[str] | None:
    slugs = sorted({slug for slug in registered_slugs if slug}, key=lambda slug: (-len(slug), slug))
    if not slugs:
        return None
    return re.compile(
        _REGISTERED_SLUG_PATTERN_TEMPLATE.format(
            slugs="|".join(re.escape(slug) for slug in slugs),
            taxonomies=_TAXONOMY_ALTERNATION,
        )
    )


def _identity_rules(
    text: str,
    *,
    own_slug: str | None,
    registered_pattern: re.Pattern[str] | None,
) -> str:
    if own_slug:
        text = _UNQUALIFIED_PROJECT_PATTERN.sub(
            lambda match: _PROJECT_IDENTITY_TEMPLATE.format(slug=own_slug, taxonomy=match.group(1)),
            text,
        )
    text = _SINGULAR_TIER_PATTERN.sub(
        lambda match: _TIER_IDENTITY_TEMPLATE.format(
            prefix=_TIER_PREFIX_BY_SINGULAR[match.group(1)], owner=match.group(2), taxonomy=match.group(3)
        ),
        text,
    )
    if registered_pattern is not None:
        text = registered_pattern.sub(
            lambda match: _PROJECT_IDENTITY_TEMPLATE.format(slug=match.group(1), taxonomy=match.group(2)),
            text,
        )
    return text


def _path_rules(text: str) -> str:
    text = _RETIRED_DOCS_PATTERN.sub(_LOCAL_DOCS_REPLACEMENT, text)
    return _RETIRED_AGENTS_PATTERN.sub(_LOCAL_AGENTS_REPLACEMENT, text)


def rewrite_layout_text(
    text: str,
    *,
    own_slug: str | None,
    registered_slugs: Iterable[str],
    markdown: bool,
) -> str:
    """Rewrite retired layout paths and unqualified identities in ``text``.

    R1 ``docs/project`` → ``docs/local`` and R5 ``agents/project`` → ``agents/local``
    apply to any text. In Markdown only: R2 ``project/<taxonomy>/`` →
    ``projects/<own_slug>/<taxonomy>/`` (only when ``own_slug`` is known), R3
    ``person|company/<slug>/<taxonomy>/`` → ``people|companies/<slug>/<taxonomy>/``,
    and R4 ``<registered slug>/<taxonomy>/`` → ``projects/<slug>/<taxonomy>/``.
    Rewritten text matches no rule, so the function is idempotent.
    """
    text = _path_rules(text)
    if not markdown:
        return text
    return _identity_rules(text, own_slug=own_slug, registered_pattern=_registered_slug_pattern(registered_slugs))


def _is_decision_record(relative_path: str) -> bool:
    return _ADR_DIRNAME in PurePosixPath(relative_path).parent.parts


def _see_also_path_rules(text: str) -> str:
    """Apply the path rules to a decision record's ``## See Also`` section only.

    A decision record's body is immutable; its See Also list is navigation, and a
    path into a moved folder follows the move or validation refuses it.
    """
    lines = text.splitlines(keepends=True)
    in_see_also = False
    for index, line in enumerate(lines):
        if line.startswith(_H2_PREFIX):
            in_see_also = line.strip() == _SEE_ALSO_HEADING
            continue
        if in_see_also:
            lines[index] = _path_rules(line)
    return "".join(lines)


def _is_excluded(relative_path: str, excluded: Sequence[str]) -> bool:
    pure = PurePosixPath(relative_path)
    if fnmatch.fnmatch(pure.name, _CHANGELOG_GLOB) or pure.name in _GENERATED_BASENAMES:
        return True
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in (*MIGRATION_BOUNDARY_GLOBS, *excluded))


def _split_nul(output: str) -> list[str]:
    return [entry for entry in output.split("\0") if entry]


def _text_candidates(repository: Repo) -> list[str]:
    return sorted(set(_split_nul(repository.git.ls_files(*_LS_FILES_ARGS))))


def _read_text_file(path: Path) -> tuple[bytes, str] | None:
    if path.is_symlink() or not path.is_file():
        return None
    raw = path.read_bytes()
    if _NUL_BYTE in raw:
        return None
    try:
        return raw, raw.decode(_UTF8)
    except UnicodeDecodeError:
        return None


def _line_mentions(relative_path: str, text: str, mention_pattern: Callable[[str], str]) -> list[str]:
    return [
        _MENTION_TEMPLATE.format(path=relative_path, line=number)
        for number, line in enumerate(text.splitlines(), start=1)
        if mention_pattern(line) != line
    ]


def _plan_rewrites(
    root: Path,
    candidates: Iterable[str],
    *,
    own_slug: str | None,
    registered_slugs: Iterable[str],
    excluded: Sequence[str],
    published_policy: PublishedIdentityPolicy,
) -> _RewritePlan:
    registered_pattern = _registered_slug_pattern(registered_slugs)
    rewrites: dict[str, tuple[bytes, bytes]] = {}
    mentions: list[str] = []
    for relative_path in candidates:
        if _is_excluded(relative_path, excluded):
            continue
        content = _read_text_file(root / relative_path)
        if content is None:
            continue
        raw, text = content
        if _is_decision_record(relative_path):
            rewritten = _see_also_path_rules(text)
            if rewritten != text:
                rewrites[relative_path] = (raw, rewritten.encode(_UTF8))
            continue
        rewritten = _path_rules(text)
        if relative_path.endswith(_MARKDOWN_SUFFIX):
            published = relative_path.startswith(_PUBLISHED_DOCS_PREFIX)
            if published and published_policy is PublishedIdentityPolicy.REPORT:
                mentions.extend(
                    _line_mentions(
                        relative_path,
                        rewritten,
                        lambda line: _identity_rules(line, own_slug=own_slug, registered_pattern=registered_pattern),
                    )
                )
            else:
                rewritten = _identity_rules(rewritten, own_slug=own_slug, registered_pattern=registered_pattern)
        if rewritten != text:
            rewrites[relative_path] = (raw, rewritten.encode(_UTF8))
    return _RewritePlan(rewrites=rewrites, published_mentions=tuple(mentions))


def rewrite_layout_references(
    root: Path,
    *,
    own_slug: str | None,
    registered_slugs: Iterable[str],
    excluded: Sequence[str] = (),
    published_policy: PublishedIdentityPolicy = PublishedIdentityPolicy.REWRITE,
) -> LayoutRewriteResult:
    """Apply :func:`rewrite_layout_text` to a checkout's text files in place.

    The input set is every tracked and every untracked, non-ignored UTF-8 text
    file. ``CHANGELOG*``, generated ``AGENTS.md``/``CLAUDE.md``/``index.yaml``,
    the migration-boundary files and the caller's ``excluded`` globs are never
    rewritten; a decision record (any ``adr`` directory) keeps its body and only
    its ``## See Also`` paths follow the move. With
    :attr:`PublishedIdentityPolicy.REPORT`, ``docs/global`` keeps its identities
    (path rules still apply) and its identity mentions are returned for the owner.
    The function never inspects dirty state; that is the caller's precondition.
    """
    repository = Repo(str(root))
    plan = _plan_rewrites(
        root,
        _text_candidates(repository),
        own_slug=own_slug,
        registered_slugs=registered_slugs,
        excluded=excluded,
        published_policy=published_policy,
    )
    for relative_path, (_, new_bytes) in plan.rewrites.items():
        (root / relative_path).write_bytes(new_bytes)
    return LayoutRewriteResult(changed_paths=tuple(sorted(plan.rewrites)), published_mentions=plan.published_mentions)


def _residue_files(root: Path, repository: Repo, retired: PurePosixPath, target: PurePosixPath) -> list[Path] | None:
    """The files of a retired directory that is only residue beside its counterpart, else ``None``.

    Residue: the counterpart exists, git tracks nothing under the retired
    directory, and every file left in it is a generated catalog or folder
    metadata. Any other file makes it a layout, which blocks as both layouts.
    """
    retired_dir = root / retired
    if not retired_dir.is_dir() or not (root / target).exists() or _tracked_under(repository, [retired]):
        return None
    files = [path for path in retired_dir.rglob("*") if not path.is_dir()]
    if any(path.name not in _RESIDUE_BASENAMES for path in files):
        return None
    return files


def _present_moves(root: Path, repository: Repo) -> tuple[tuple[PurePosixPath, PurePosixPath], ...]:
    return tuple(
        (retired, target)
        for retired, target in LAYOUT_MOVES
        if (root / retired).exists() and _residue_files(root, repository, retired, target) is None
    )


def _remove_residue(root: Path, repository: Repo) -> tuple[str, ...]:
    """Remove each retired directory that is only residue; return the removed files."""
    removed: list[str] = []
    for retired, target in LAYOUT_MOVES:
        files = _residue_files(root, repository, retired, target)
        if files is None:
            continue
        removed.extend(str(path.relative_to(root)) for path in files)
        shutil.rmtree(root / retired)
    return tuple(sorted(removed))


def _moved_path(relative_path: str, moves: Sequence[tuple[PurePosixPath, PurePosixPath]]) -> str:
    pure = PurePosixPath(relative_path)
    for retired, target in moves:
        if pure == retired or retired in pure.parents:
            return str(target / pure.relative_to(retired))
    return relative_path


def _under_any(relative_path: str, directories: Iterable[PurePosixPath]) -> bool:
    pure = PurePosixPath(relative_path)
    return any(pure == directory or directory in pure.parents for directory in directories)


def _status_entries(repository: Repo) -> list[tuple[str, str]]:
    """Return ``(status code, path)`` for every changed or untracked path."""
    entries = _split_nul(repository.git.status(*_STATUS_ARGS))
    parsed: list[tuple[str, str]] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        code, path = entry[:2], entry[3:]
        parsed.append((code, path))
        if code[0] in _STATUS_RENAME_CODES:
            index += 1
            if index < len(entries):
                parsed.append((code, entries[index]))
        index += 1
    return parsed


def _dirty_touched_paths(repository: Repo, plan: _MovePlan) -> tuple[str, ...]:
    retired = [retired for retired, _ in plan.moves]
    touched = set(plan.tracked_moved) | set(plan.rewrite_plan.rewrites)
    blocking: set[str] = set()
    for code, path in _status_entries(repository):
        if code == _STATUS_UNTRACKED:
            if path in touched or _under_any(path, retired):
                blocking.add(path)
            continue
        if path in touched:
            blocking.add(path)
    return tuple(sorted(blocking))


def _linked_worktrees(repository: Repo, root: Path) -> tuple[str, ...]:
    try:
        output = repository.git.worktree(*_WORKTREE_LIST_ARGS)
    except GitCommandError:
        return ()
    worktrees = [
        line[len(_WORKTREE_LINE_PREFIX) :] for line in output.splitlines() if line.startswith(_WORKTREE_LINE_PREFIX)
    ]
    resolved_root = root.resolve()
    return tuple(path for path in worktrees if Path(path).resolve() != resolved_root)


def _upstream_converged(repository: Repo, fetcher: Fetcher) -> bool:
    """Whether the fetched upstream tip already carries the converged layout."""
    try:
        tracking = repository.active_branch.tracking_branch()
    except TypeError:
        return False
    if tracking is None or not fetcher(repository):
        return False
    try:
        entries = set(_split_nul(repository.git.ls_tree(*_LS_TREE_ARGS, "-z", tracking.path, _DOCS_DIR + "/")))
        entries |= set(_split_nul(repository.git.ls_tree(*_LS_TREE_ARGS, "-z", tracking.path, _AGENTS_DIR + "/")))
    except GitCommandError:
        return False
    retired_present = any(str(retired) in entries for retired, _ in LAYOUT_MOVES)
    target_present = any(str(target) in entries for _, target in LAYOUT_MOVES)
    return target_present and not retired_present


def _tracked_under(repository: Repo, directories: Sequence[PurePosixPath]) -> tuple[str, ...]:
    if not directories:
        return ()
    output = repository.git.ls_files(*_LS_FILES_TRACKED_ARGS, _PATHSPEC_SEPARATOR, *(str(path) for path in directories))
    return tuple(sorted(_split_nul(output)))


def _plan_convergence(
    root: Path,
    repository: Repo,
    *,
    own_slug: str,
    registered_slugs: Sequence[str],
) -> _MovePlan:
    moves = _present_moves(root, repository)
    tracked_moved = _tracked_under(repository, [retired for retired, _ in moves])
    rewrite_plan = _plan_rewrites(
        root,
        _text_candidates(repository),
        own_slug=own_slug,
        registered_slugs=registered_slugs,
        excluded=(),
        published_policy=PublishedIdentityPolicy.REPORT,
    )
    return _MovePlan(moves=moves, tracked_moved=tracked_moved, rewrite_plan=rewrite_plan)


def _index_entries(repository: Repo, paths: Sequence[str]) -> dict[str, str]:
    if not paths:
        return {}
    output = repository.git.ls_files(*_LS_FILES_STAGE_ARGS, _PATHSPEC_SEPARATOR, *paths)
    entries: dict[str, str] = {}
    for entry in _split_nul(output):
        metadata, path = entry.split("\t", 1)
        entries[path] = metadata
    return entries


def _apply_moves(root: Path, plan: _MovePlan) -> None:
    """Rename each retired directory on the filesystem, leaving the index to the commit.

    The move is not staged as a rename: the sealed commit admits a declared
    path only when it carries a change git will record, and a staged rename
    hides its old side. Left unstaged, the old paths read as deleted and the new
    ones as added, and the commit records them as renames.
    """
    for retired, target in plan.moves:
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        os.rename(root / retired, root / target)


def _expected_commit_paths(plan: _MovePlan) -> set[str]:
    rewritten = {_moved_path(path, plan.moves) for path in plan.rewrite_plan.rewrites}
    moved_targets = {_moved_path(path, plan.moves) for path in plan.tracked_moved}
    return set(plan.tracked_moved) | moved_targets | rewritten


def _committed_paths(repository: Repo, commit: str) -> set[str]:
    return set(_split_nul(repository.git.diff_tree(*_DIFF_TREE_ARGS, commit)))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inventory_moves(root: Path, plan: _MovePlan) -> tuple[dict[str, _MovedFile], tuple[str, ...]]:
    """Record every file and directory each move will relocate, keyed by its new path."""
    files: dict[str, _MovedFile] = {}
    directories: list[str] = []
    for retired, target in plan.moves:
        retired_dir = root / retired
        directories.append(str(retired))
        for path in sorted(retired_dir.rglob("*")):
            relative = path.relative_to(retired_dir)
            if path.is_dir() and not path.is_symlink():
                directories.append(str(retired / relative))
                continue
            files[str(target / relative)] = _MovedFile(
                retired_path=str(retired / relative), digest=_digest(path.read_bytes())
            )
    return files, tuple(directories)


def _prune_empty_directories(directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if not any(directory.iterdir()):
        directory.rmdir()


def _restore_files(
    root: Path,
    plan: _MovePlan,
    moved: dict[str, _MovedFile],
    directories: Sequence[str],
    written: dict[str, tuple[bytes, bytes]],
) -> list[str]:
    """Move this run's own files back one by one; return the paths left where they are.

    A file stays at its current path, and is named, when another writer changed
    it, created it, or occupies its original path. Moving files individually
    means a preserved file is never relocated by restoring its directory.
    """
    conflicts: list[str] = []
    for written_path, (original, rewritten) in written.items():
        if written_path in moved:
            continue
        written_file = root / written_path
        if written_file.is_file() and written_file.read_bytes() == rewritten:
            written_file.write_bytes(original)
        else:
            conflicts.append(written_path)
    for relative in directories:
        (root / relative).mkdir(parents=True, exist_ok=True)
    for new_path, record in moved.items():
        current = root / new_path
        if not current.exists() and not current.is_symlink():
            conflicts.append(new_path)
            continue
        expected = written.get(new_path)
        current_bytes = current.read_bytes()
        if expected is not None:
            if current_bytes != expected[1]:
                conflicts.append(new_path)
                continue
            current.write_bytes(expected[0])
        elif _digest(current_bytes) != record.digest:
            conflicts.append(new_path)
            continue
        destination = root / record.retired_path
        if destination.exists() or destination.is_symlink():
            conflicts.append(new_path)
            continue
        os.rename(current, destination)
    for _, target in plan.moves:
        target_dir = root / target
        if target_dir.is_dir():
            conflicts.extend(
                str(path.relative_to(root))
                for path in sorted(target_dir.rglob("*"))
                if not path.is_dir() and str(path.relative_to(root)) not in moved
            )
            _prune_empty_directories(target_dir)
    return conflicts


def _restore_own_changes(
    root: Path,
    repository: Repo,
    plan: _MovePlan,
    moved: dict[str, _MovedFile],
    directories: Sequence[str],
    written: dict[str, tuple[bytes, bytes]],
    index_snapshots: Sequence[dict[str, str]],
    touched: Sequence[str],
) -> tuple[str, ...]:
    """Reverse only convergence's own delta; return the paths left as found.

    A touched path's index entry is reset only when it still equals one this run
    observed (before its effects or after its own staging).
    """
    conflicts = _restore_files(root, plan, moved, directories, written)
    current_index = _index_entries(repository, touched)
    restorable = [
        path for path in touched if any(current_index.get(path) == snapshot.get(path) for snapshot in index_snapshots)
    ]
    conflicts.extend(path for path in touched if path not in restorable)
    if restorable:
        repository.git.reset(*_RESET_ARGS, _PATHSPEC_SEPARATOR, *restorable)
    return tuple(sorted(set(conflicts)))


def _incomplete_paths(repository: Repo, root: Path) -> tuple[str, ...]:
    """Retired directories the recorded tree still tracks but the checkout no longer has.

    A migration interrupted after its move leaves the retired directory absent
    while ``HEAD`` still records it; such a root is unresolved, never current.
    """
    incomplete: list[str] = []
    if not repository.head.is_valid():
        return ()
    for retired, _ in LAYOUT_MOVES:
        if (root / retired).exists():
            continue
        try:
            tracked = _split_nul(
                repository.git.ls_tree(*_LS_TREE_RECURSIVE_ARGS, _HEAD_REF, _PATHSPEC_SEPARATOR, str(retired))
            )
        except GitCommandError:
            continue
        if tracked:
            incomplete.append(str(retired))
    return tuple(incomplete)


def _log_result(result: LayoutConvergenceResult) -> LayoutConvergenceResult:
    logger.info(
        _LOG_ROOT_EVENT,
        project_root=str(result.root),
        outcome=result.outcome.value,
        touched=len(result.touched_paths),
        blocking=list(result.blocking_paths),
        published_mentions=len(result.published_mentions),
        worktrees=len(result.worktrees),
        commit=result.commit,
        removed_residue=len(result.removed_residue),
    )
    return result


def assess_root(
    root: Path,
    *,
    registered_slugs: Sequence[str],
    fetcher: Fetcher,
) -> LayoutConvergenceResult | None:
    """Return a terminal outcome that needs no write, or ``None`` when the root would converge."""
    repository = Repo(str(root))
    worktrees = _linked_worktrees(repository, root)
    moves = _present_moves(root, repository)
    incomplete = _incomplete_paths(repository, root)
    if incomplete:
        return LayoutConvergenceResult(
            root=root,
            outcome=LayoutConvergenceOutcome.BLOCKED_INCOMPLETE,
            blocking_paths=incomplete,
            worktrees=worktrees,
        )
    if not moves:
        return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.CURRENT, worktrees=worktrees)
    both = tuple(str(target) for _, target in moves if (root / target).exists())
    if both:
        return LayoutConvergenceResult(
            root=root, outcome=LayoutConvergenceOutcome.BLOCKED_BOTH_LAYOUTS, blocking_paths=both, worktrees=worktrees
        )
    try:
        own_slug = read_declared_project_slug(root)
    except UndeclaredProjectSlugError:
        return LayoutConvergenceResult(
            root=root, outcome=LayoutConvergenceOutcome.BLOCKED_UNDECLARED_SLUG, worktrees=worktrees
        )
    if _upstream_converged(repository, fetcher):
        return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.PULL_REQUIRED, worktrees=worktrees)
    plan = _plan_convergence(root, repository, own_slug=own_slug, registered_slugs=registered_slugs)
    blocking = _dirty_touched_paths(repository, plan)
    if blocking:
        return LayoutConvergenceResult(
            root=root, outcome=LayoutConvergenceOutcome.BLOCKED_DIRTY, blocking_paths=blocking, worktrees=worktrees
        )
    return None


def converge_root(
    root: Path,
    *,
    registered_slugs: Sequence[str],
    committer: Committer,
    fetcher: Fetcher,
) -> LayoutConvergenceResult:
    """Converge one repository to the documentation layout, or report why not.

    Moves ``docs/project``/``agents/project`` to their ``local`` counterparts,
    rewrites references, and commits exactly those paths through ``committer``.
    A refused commit or a failed write reverses only this run's own bytes, file
    moves and index entries; anything another writer changed meanwhile is left
    where and as found and reported as a restore conflict. A retired directory left as residue
    beside its converged counterpart is removed first.
    """
    removed_residue = _remove_residue(root, Repo(str(root)))
    terminal = assess_root(root, registered_slugs=registered_slugs, fetcher=fetcher)
    if terminal is not None:
        return _log_result(replace(terminal, removed_residue=removed_residue))
    repository = Repo(str(root))
    worktrees = _linked_worktrees(repository, root)
    own_slug = read_declared_project_slug(root)
    plan = _plan_convergence(root, repository, own_slug=own_slug, registered_slugs=registered_slugs)
    mentions = plan.rewrite_plan.published_mentions

    expected = _expected_commit_paths(plan)
    touched = tuple(sorted(expected))
    moved, directories = _inventory_moves(root, plan)
    index_snapshots: list[dict[str, str]] = [_index_entries(repository, touched)]
    written: dict[str, tuple[bytes, bytes]] = {}
    try:
        _apply_moves(root, plan)
        for relative_path, (original, rewritten) in plan.rewrite_plan.rewrites.items():
            moved_path = _moved_path(relative_path, plan.moves)
            (root / moved_path).write_bytes(rewritten)
            written[moved_path] = (original, rewritten)
        # Stage only the new side: the old paths stay unstaged deletions, so the
        # sealed commit can see them, and the committer has nothing left to stage
        # that this run's index snapshot does not already record.
        added = sorted({_moved_path(path, plan.moves) for path in plan.tracked_moved} | set(written))
        if touched and added:
            repository.git.add(_PATHSPEC_SEPARATOR, *added)
        index_snapshots.append(_index_entries(repository, touched))
    except (OSError, GitCommandError):
        logger.exception(_LOG_EFFECT_FAILED_EVENT, project_root=str(root))
        conflicts = _restore_own_changes(root, repository, plan, moved, directories, written, index_snapshots, touched)
        return _log_result(
            LayoutConvergenceResult(
                root=root,
                outcome=LayoutConvergenceOutcome.RESTORE_CONFLICT if conflicts else LayoutConvergenceOutcome.FAILED,
                touched_paths=touched,
                blocking_paths=conflicts,
                worktrees=worktrees,
            )
        )
    if not touched:
        return _log_result(
            LayoutConvergenceResult(
                root=root,
                outcome=LayoutConvergenceOutcome.MIGRATED_UNTRACKED,
                published_mentions=mentions,
                worktrees=worktrees,
            )
        )

    previous_head = repository.head.commit.hexsha
    try:
        committer(root, touched)
    except LayoutCommitRefused:
        pass
    current_head = repository.head.commit.hexsha
    if current_head != previous_head and _committed_paths(repository, current_head) == expected:
        return _log_result(
            LayoutConvergenceResult(
                root=root,
                outcome=LayoutConvergenceOutcome.MIGRATED_COMMITTED,
                touched_paths=touched,
                published_mentions=mentions,
                worktrees=worktrees,
                commit=current_head,
            )
        )
    if current_head != previous_head:
        return _log_result(
            LayoutConvergenceResult(
                root=root,
                outcome=LayoutConvergenceOutcome.RESTORE_CONFLICT,
                touched_paths=touched,
                blocking_paths=(current_head,),
                worktrees=worktrees,
                commit=current_head,
            )
        )
    conflicts = _restore_own_changes(root, repository, plan, moved, directories, written, index_snapshots, touched)
    outcome = (
        LayoutConvergenceOutcome.RESTORE_CONFLICT
        if conflicts
        else LayoutConvergenceOutcome.RESTORED_AFTER_REFUSED_COMMIT
    )
    return _log_result(
        LayoutConvergenceResult(
            root=root, outcome=outcome, touched_paths=touched, blocking_paths=conflicts, worktrees=worktrees
        )
    )

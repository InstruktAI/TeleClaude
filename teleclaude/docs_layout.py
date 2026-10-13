"""Converge a repository to the documentation layout the context domain reads.

The layout is local documentation under ``docs/local``, local agent artifacts
under ``agents/local``, and snippet references in qualified identity forms.
Project-local, person-local and company-local snippets use
``local/projects/<slug>/…``, ``local/people/<slug>/…`` and
``local/companies/<slug>/…``. Published person and company snippets retain
``people/<slug>/…`` and ``companies/<slug>/…``. This module is the migration
boundary: it is the one place that names the retired layout, because its job is
to read it as input.

``rewrite_layout_text`` is the pure identifier-level rewrite shared by every
caller. ``rewrite_layout_references`` applies it to a checkout's text files,
and ``converge_root`` moves one repository and commits it through an injected
committer, restoring only its own changes when that commit is refused.
``repository_convergence_lock`` lets callers run one convergence at a time per
repository.
The contract is ``local/projects/teleclaude/spec/feature/context/documentation-layout-convergence``.
"""

from __future__ import annotations

import fcntl
import fnmatch
import re
import shutil
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, assert_never

from instrukt_ai_logging import get_logger

from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.docs_layout_effects import (
    PATHSPEC_SEPARATOR,
    PerformedEffects,
    apply_moves,
    index_entries,
    restore_own_changes,
    split_nul,
    stage_paths,
)
from teleclaude.domains import valid_domains
from teleclaude.git import GitCommandError, Repo
from teleclaude.snippet_validation import (
    RESERVED_SNIPPET_ID_PREFIXES,
    UndeclaredProjectSlugError,
    read_declared_project_slug,
)

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
_RETIRED_DOCS_TOKEN: Final = str(_RETIRED_DOCS)
_RETIRED_AGENTS_TOKEN: Final = str(_RETIRED_AGENTS)
_UNQUALIFIED_PROJECT_TOKEN: Final = "project/"
_TIER_PREFIX_BY_SINGULAR: Final[dict[str, str]] = {"person": "people", "company": "companies"}
_SINGULAR_TIER_TOKENS: Final = tuple(f"{prefix}/" for prefix in _TIER_PREFIX_BY_SINGULAR)
_QUALIFIED_PROJECT_TOKEN: Final = "projects/"

_TAXONOMY_ALTERNATION: Final = "|".join(sorted(TAXONOMY_TYPES))
_RETIRED_DOCS_PATTERN: Final = re.compile(rf"(?<![\w.-]){re.escape(_RETIRED_DOCS_TOKEN)}(?=/|\b)")
_RETIRED_AGENTS_PATTERN: Final = re.compile(rf"(?<![\w.-]){re.escape(_RETIRED_AGENTS_TOKEN)}(?=/|\b)")
_LOCAL_DOCS_REPLACEMENT: Final = "docs/local"
_LOCAL_AGENTS_REPLACEMENT: Final = "agents/local"
_UNQUALIFIED_PROJECT_PATTERN: Final = re.compile(
    rf"(?<![\w./-]){re.escape(_UNQUALIFIED_PROJECT_TOKEN)}({_TAXONOMY_ALTERNATION})/"
)
_PROJECT_IDENTITY_TEMPLATE: Final = "local/projects/{slug}/{taxonomy}/"
_QUALIFIED_PROJECT_IDENTITY_TEMPLATE: Final = "local/projects/{slug}/{tail}"
_SINGULAR_TIER_PATTERN: Final = re.compile(
    rf"(?<![\w./-])({'|'.join(re.escape(prefix) for prefix in _TIER_PREFIX_BY_SINGULAR)})/"
    rf"([a-z0-9-]+)/({_TAXONOMY_ALTERNATION})/"
)
_TIER_IDENTITY_TEMPLATE: Final = "{prefix}/{owner}/{taxonomy}/"
_REGISTERED_SLUG_PATTERN_TEMPLATE: Final = r"(?<![\w./-])({slugs})/({taxonomies})/"
_QUALIFIED_PROJECT_PATTERN_TEMPLATE: Final = (
    rf"(?<![\w./-]){re.escape(_QUALIFIED_PROJECT_TOKEN)}({{slugs}})/((?:{{taxonomies}}/)|…)"
)
_REGEX_ALTERNATION_SEPARATOR: Final = "|"
_PROJECT_IDENTITY_PLACEHOLDERS: Final = ("<slug>", "{slug}", "{project}")
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
_STATUS_ARGS: Final = ("--porcelain=v1", "-z", "--untracked-files=all")
_STATUS_UNTRACKED: Final = "??"
_STATUS_RENAME_CODES: Final = frozenset({"R", "C"})
_DIFF_TREE_ARGS: Final = ("--no-commit-id", "--name-only", "-r", "--no-renames", "-z")
_LS_TREE_ARGS: Final = ("--name-only",)
_WORKTREE_LIST_ARGS: Final = ("list", "--porcelain")
_WORKTREE_LINE_PREFIX: Final = "worktree "
_MENTION_TEMPLATE: Final = "{path}:{line}"

_CONVERGENCE_LOCK_FILENAME: Final = "teleclaude-docs-layout-convergence.lock"
_LOCK_FILE_MODE: Final = "a"

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
    FOREIGN_CHECKOUT = "foreign_checkout"


class LayoutResultClass(StrEnum):
    """What a per-root outcome means to whoever ran convergence, least to most severe."""

    SETTLED = "settled"
    HELD = "held"
    FAILURE = "failure"


_CLASS_SEVERITY: Final = (LayoutResultClass.SETTLED, LayoutResultClass.HELD, LayoutResultClass.FAILURE)


def outcome_class(outcome: LayoutConvergenceOutcome) -> LayoutResultClass:
    """Classify one outcome: settled, held for its owner or deferred, or a failure.

    Held outcomes are convergence correctly leaving an owner's work alone or lacking
    an attributable party. Failures are an operation that failed, a commit that was
    refused, or a restore that left conflicts.
    """
    match outcome:
        case (
            LayoutConvergenceOutcome.CURRENT
            | LayoutConvergenceOutcome.MIGRATED_COMMITTED
            | LayoutConvergenceOutcome.MIGRATED_UNTRACKED
            | LayoutConvergenceOutcome.PULL_REQUIRED
            | LayoutConvergenceOutcome.UNAVAILABLE
            | LayoutConvergenceOutcome.FOREIGN_CHECKOUT
        ):
            return LayoutResultClass.SETTLED
        case (
            LayoutConvergenceOutcome.BLOCKED_BOTH_LAYOUTS
            | LayoutConvergenceOutcome.BLOCKED_UNDECLARED_SLUG
            | LayoutConvergenceOutcome.BLOCKED_DIRTY
            | LayoutConvergenceOutcome.BLOCKED_INCOMPLETE
            | LayoutConvergenceOutcome.DEFERRED_NO_IDENTITY
        ):
            return LayoutResultClass.HELD
        case (
            LayoutConvergenceOutcome.RESTORED_AFTER_REFUSED_COMMIT
            | LayoutConvergenceOutcome.RESTORE_CONFLICT
            | LayoutConvergenceOutcome.FAILED
        ):
            return LayoutResultClass.FAILURE
        case _:
            return assert_never(outcome)


def run_class(results: Iterable[LayoutConvergenceResult]) -> LayoutResultClass:
    """The most severe class among a run's roots; a run with no roots is settled."""
    return max(
        (outcome_class(result.outcome) for result in results),
        key=_CLASS_SEVERITY.index,
        default=LayoutResultClass.SETTLED,
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
    catalog_refresh: str | None = None


@dataclass(frozen=True)
class _RewritePlan:
    """Planned rewrites keyed by checkout-relative path: (bytes read, bytes to write)."""

    rewrites: dict[str, tuple[bytes, bytes]] = field(default_factory=dict)
    published_mentions: tuple[str, ...] = ()


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


def _qualified_project_pattern(registered_slugs: Iterable[str]) -> re.Pattern[str] | None:
    slugs = sorted({slug for slug in registered_slugs if slug}, key=lambda slug: (-len(slug), slug))
    slug_alternation = _REGEX_ALTERNATION_SEPARATOR.join(
        [*(re.escape(slug) for slug in slugs), *(re.escape(value) for value in _PROJECT_IDENTITY_PLACEHOLDERS)]
    )
    return re.compile(
        _QUALIFIED_PROJECT_PATTERN_TEMPLATE.format(slugs=slug_alternation, taxonomies=_TAXONOMY_ALTERNATION)
    )


def registered_project_slugs(roots: Sequence[Path]) -> tuple[str, ...]:
    """Return present registered project slugs that cannot be mistaken for domains."""
    excluded = valid_domains() | RESERVED_SNIPPET_ID_PREFIXES
    slugs: set[str] = set()
    for root in roots:
        try:
            slug = read_declared_project_slug(root)
        except (UndeclaredProjectSlugError, ValueError):
            continue
        if slug not in excluded:
            slugs.add(slug)
    return tuple(sorted(slugs))


def _identity_rules(
    text: str,
    *,
    own_slug: str | None,
    registered_pattern: re.Pattern[str] | None,
    qualified_project_pattern: re.Pattern[str] | None,
) -> str:
    if own_slug and _UNQUALIFIED_PROJECT_TOKEN in text:
        text = _UNQUALIFIED_PROJECT_PATTERN.sub(
            lambda match: _PROJECT_IDENTITY_TEMPLATE.format(slug=own_slug, taxonomy=match.group(1)),
            text,
        )
    if any(token in text for token in _SINGULAR_TIER_TOKENS):
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
    if qualified_project_pattern is not None and _QUALIFIED_PROJECT_TOKEN in text:
        text = qualified_project_pattern.sub(
            lambda match: _QUALIFIED_PROJECT_IDENTITY_TEMPLATE.format(slug=match.group(1), tail=match.group(2)),
            text,
        )
    return text


def _path_rules(text: str) -> str:
    if _RETIRED_DOCS_TOKEN in text:
        text = _RETIRED_DOCS_PATTERN.sub(_LOCAL_DOCS_REPLACEMENT, text)
    if _RETIRED_AGENTS_TOKEN in text:
        text = _RETIRED_AGENTS_PATTERN.sub(_LOCAL_AGENTS_REPLACEMENT, text)
    return text


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
    ``local/projects/<own_slug>/<taxonomy>/`` (only when ``own_slug`` is known), R3
    ``person|company/<slug>/<taxonomy>/`` → ``people|companies/<slug>/<taxonomy>/``,
    and R4 ``<registered slug>/<taxonomy>/`` → ``local/projects/<slug>/<taxonomy>/``;
    qualified project identities with a registered slug or a supported placeholder
    are prefixed with ``local/``. Rewritten text matches no rule, so the function is idempotent.
    """
    text = _path_rules(text)
    if not markdown:
        return text
    return _identity_rules(
        text,
        own_slug=own_slug,
        registered_pattern=_registered_slug_pattern(registered_slugs),
        qualified_project_pattern=_qualified_project_pattern(registered_slugs),
    )


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


def _text_candidates(repository: Repo) -> list[str]:
    return sorted(set(split_nul(repository.git.ls_files(*_LS_FILES_ARGS))))


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
    qualified_project_pattern = _qualified_project_pattern(registered_slugs)
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
                        lambda line: _identity_rules(
                            line,
                            own_slug=own_slug,
                            registered_pattern=registered_pattern,
                            qualified_project_pattern=qualified_project_pattern,
                        ),
                    )
                )
            else:
                rewritten = _identity_rules(
                    rewritten,
                    own_slug=own_slug,
                    registered_pattern=registered_pattern,
                    qualified_project_pattern=qualified_project_pattern,
                )
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
    entries = split_nul(repository.git.status(*_STATUS_ARGS))
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
        entries = set(split_nul(repository.git.ls_tree(*_LS_TREE_ARGS, "-z", tracking.path, _DOCS_DIR + "/")))
        entries |= set(split_nul(repository.git.ls_tree(*_LS_TREE_ARGS, "-z", tracking.path, _AGENTS_DIR + "/")))
    except GitCommandError:
        return False
    retired_present = any(str(retired) in entries for retired, _ in LAYOUT_MOVES)
    target_present = any(str(target) in entries for _, target in LAYOUT_MOVES)
    return target_present and not retired_present


def _tracked_under(repository: Repo, directories: Sequence[PurePosixPath]) -> tuple[str, ...]:
    if not directories:
        return ()
    output = repository.git.ls_files(*_LS_FILES_TRACKED_ARGS, PATHSPEC_SEPARATOR, *(str(path) for path in directories))
    return tuple(sorted(split_nul(output)))


def _plan_convergence(
    root: Path,
    repository: Repo,
    *,
    own_slug: str | None,
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


def _expected_commit_paths(plan: _MovePlan) -> set[str]:
    rewritten = {_moved_path(path, plan.moves) for path in plan.rewrite_plan.rewrites}
    moved_targets = {_moved_path(path, plan.moves) for path in plan.tracked_moved}
    return set(plan.tracked_moved) | moved_targets | rewritten


def _committed_paths(repository: Repo, commit: str) -> set[str]:
    return set(split_nul(repository.git.diff_tree(*_DIFF_TREE_ARGS, commit)))


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
            tracked = split_nul(
                repository.git.ls_tree(*_LS_TREE_RECURSIVE_ARGS, _HEAD_REF, PATHSPEC_SEPARATOR, str(retired))
            )
        except GitCommandError:
            continue
        if tracked:
            incomplete.append(str(retired))
    return tuple(incomplete)


@contextmanager
def repository_convergence_lock(root: Path, on_contention: Callable[[], None] | None = None) -> Iterator[None]:
    """Hold the exclusive lock that lets one convergence at a time work on one repository.

    The lock lives in the repository's git common directory, so every checkout and
    every registered root of the repository contends on it and the working tree
    never sees it. A convergence already holding it makes the caller wait;
    ``on_contention`` is called once before it does, so the caller can say so. The
    kernel releases the lock when its holder exits, so no run can leave it held.
    """
    lock_path = Path(Repo(str(root)).common_dir).resolve() / _CONVERGENCE_LOCK_FILENAME
    with lock_path.open(_LOCK_FILE_MODE, encoding=_UTF8) as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if on_contention is not None:
                on_contention()
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
        catalog_refresh=result.catalog_refresh,
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
        try:
            own_slug = read_declared_project_slug(root)
        except UndeclaredProjectSlugError:
            own_slug = None
        plan = _plan_convergence(root, repository, own_slug=own_slug, registered_slugs=registered_slugs)
        if not plan.rewrite_plan.rewrites:
            return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.CURRENT, worktrees=worktrees)
        blocking = _dirty_touched_paths(repository, plan)
        if blocking:
            return LayoutConvergenceResult(
                root=root, outcome=LayoutConvergenceOutcome.BLOCKED_DIRTY, blocking_paths=blocking, worktrees=worktrees
            )
        return None
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
    A refused commit or a failed write reverses only the effects this run
    performed: its own bytes, file moves and index entries. Anything another
    writer changed meanwhile is left where and as found and reported as a
    restore conflict. A retired directory left as residue
    beside its converged counterpart is removed first.
    """
    removed_residue = _remove_residue(root, Repo(str(root)))
    terminal = assess_root(root, registered_slugs=registered_slugs, fetcher=fetcher)
    if terminal is not None:
        return _log_result(replace(terminal, removed_residue=removed_residue))
    repository = Repo(str(root))
    worktrees = _linked_worktrees(repository, root)
    try:
        own_slug = read_declared_project_slug(root)
    except UndeclaredProjectSlugError:
        own_slug = None
    plan = _plan_convergence(root, repository, own_slug=own_slug, registered_slugs=registered_slugs)
    mentions = plan.rewrite_plan.published_mentions

    expected = _expected_commit_paths(plan)
    touched = tuple(sorted(expected))
    performed = PerformedEffects(index_snapshots=[index_entries(repository, touched)])
    try:
        apply_moves(root, plan.moves, performed)
        for relative_path, (original, rewritten) in plan.rewrite_plan.rewrites.items():
            moved_path = _moved_path(relative_path, plan.moves)
            (root / moved_path).write_bytes(rewritten)
            performed.written[moved_path] = (original, rewritten)
        # Stage only the new side: the old paths stay unstaged deletions, so the
        # sealed commit can see them, and the committer has nothing left to stage
        # that this run's index snapshot does not already record.
        added = sorted({_moved_path(path, plan.moves) for path in plan.tracked_moved} | set(performed.written))
        if touched and added:
            stage_paths(repository, added, performed)
        performed.index_snapshots.append(index_entries(repository, touched))
    except (OSError, GitCommandError):
        logger.exception(_LOG_EFFECT_FAILED_EVENT, project_root=str(root))
        conflicts = restore_own_changes(root, repository, performed)
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
    conflicts = restore_own_changes(root, repository, performed)
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

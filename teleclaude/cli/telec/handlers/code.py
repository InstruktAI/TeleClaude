"""CLI handlers for ``telec code`` namespace."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.handlers.quality import handle_format, handle_install, handle_lint, handle_test
from teleclaude.cli.telec.help import _usage
from teleclaude.constants import CHECKPOINT_FILE_CATEGORIES, FileCategory
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_lock import main_branch_lock, wait_for_index_lock_clear
from teleclaude.hooks.checkpoint_flags import record_authored_main_commit, record_commit_obligations
from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)
from teleclaude.session_identity import get_session_id, get_system_role

logger = get_logger(__name__)

# Mandated commit trailer (repo Commits policy). Auto-appended so it can never
# be forgotten; idempotent — skipped if the message already carries it.
_COMMIT_TRAILER = (
    "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
    "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
)
_TRAILER_MARKER = "🤖 Generated with [TeleClaude]"
_COMMIT_MESSAGE_RE = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+")
_DOC_COMMIT_PATTERNS = ["docs/**", "*.md", "*.txt", "*.rst"]


def _with_trailer(message: str) -> str:
    """Return the message with the mandated trailer appended (idempotent)."""
    body = message.rstrip()
    if _TRAILER_MARKER not in body:
        body = f"{body}\n\n{_COMMIT_TRAILER}"
    return body + "\n"


def handle_code(args: list[str]) -> None:
    """Route ``telec code <subcommand>`` to the correct handler."""
    if not args:
        print(_usage("code"))
        return
    sub = args[0]
    rest = args[1:]
    if sub == "lint":
        handle_lint(rest)
    elif sub == "test":
        handle_test(rest)
    elif sub == "format":
        handle_format(rest)
    elif sub == "install":
        handle_install(rest)
    elif sub == "commit":
        handle_code_commit(rest)
    elif sub == "changed":
        handle_code_changed(rest)
    elif sub == "add":
        handle_code_add(rest)
    else:
        print(_usage("code"))


def handle_code_add(args: list[str]) -> None:
    """Stage files for the next commit.

    Sealed equivalent of ``git add`` for the three cases git's data model
    genuinely requires staging:

    1. **Untracked (NEW) files** — git refuses ``git commit -- <newfile>``
       until the path enters the index.
    2. **Unmerged-index files** (post-conflict, pre-resolution-stage) —
       git refuses a commit while the index has unmerged entries; the
       file must be marked resolved via ``git add``.
    3. **Partial-staged tracked files** (staged hunks + later working-tree
       delta) — the partial-staging guard in ``telec code commit`` blocks
       these because ``git commit -- <path>`` would otherwise sweep
       unstaged hunks. This command is that guard's prescribed recovery:
       running ``git add`` fully restages the file so the staged version
       matches the working tree, removing the ambiguity.

    Modified-tracked files that are NOT partial-staged are no-ops here
    (the pathspec commit picks them up directly from the working tree).
    Clean paths and missing paths error with the path named.
    """
    positionals: list[str] = []
    for token in args:
        if token.startswith("-"):
            print(
                f"ERROR: unknown flag: {token}\nUsage: telec code add <path> [<path> ...]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        positionals.append(token)

    if not positionals:
        print(
            "Usage: telec code add <path> [<path> ...]\n"
            "\n"
            "Stages NEW files (untracked) so the next `telec code commit` includes them.\n"
            "Modified files don't need to be added — pathspec commits them straight from\n"
            "the working tree.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    project_root = resolve_git_root(resolve_invocation_cwd())
    untracked = set(_get_untracked_files(project_root))
    unmerged = set(_get_unmerged_files(project_root))
    dirty = _dirty_paths(project_root)
    # Partial-staging: file has BOTH staged changes AND a later working-tree
    # delta. `telec code add` is the recovery path the partial-staging guard
    # points at, so it must accept these files and fully (re)stage them.
    repo = Repo(str(project_root))
    staged_now = set(repo.git.diff("--cached", "--name-only").strip().splitlines())
    unstaged_now = set(repo.git.diff("--name-only").strip().splitlines())
    partial_staged = staged_now & unstaged_now

    stageable: list[str] = []
    already_tracked: list[str] = []
    clean: list[str] = []
    missing: list[str] = []

    for path in positionals:
        full = project_root / path
        # Stageable classes are checked BEFORE existence: a partial-staged
        # tracked file with a pending DELETION has staged content (so git
        # knows the path) but no working-tree file, and the recovery path
        # must still accept it. Untracked/unmerged files all exist on disk
        # by construction, so this ordering does not weaken those checks.
        if path in untracked or path in unmerged or path in partial_staged:
            stageable.append(path)
        elif not full.exists():
            missing.append(path)
        elif path in dirty:
            already_tracked.append(path)
        else:
            clean.append(path)

    if missing:
        print(
            "ERROR: path(s) not found in working tree:\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if clean:
        print(
            "ERROR: path(s) have no changes to stage:\n  " + "\n  ".join(clean),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if already_tracked:
        # Friendly no-op explanation: modified-tracked files don't need add.
        print(
            "Note: already tracked + modified, no `add` needed (the pathspec\n"
            "commit takes them straight from the working tree):\n  " + "\n  ".join(already_tracked),
            file=sys.stderr,
        )

    if stageable:
        _stage_files(stageable, project_root)
        # "Staged" without "new" — this command also handles unmerged and
        # partial-staged tracked recoveries, so the diagnostic stays neutral.
        print(f"Staged {len(stageable)} file(s):")
        for path in stageable:
            print(f"  {path}")


def handle_code_changed(args: list[str]) -> None:
    """List workspace-scoped changed files."""
    _ = args
    project_root = resolve_git_root(resolve_invocation_cwd())
    scope_resolution = resolve_workspace_scope_resolution(project_root)
    files = _changed_paths(scope_resolution)
    if not files:
        print("No uncommitted workspace-scoped changes.")
        return
    for f in sorted(files):
        print(f)


def handle_code_commit(args: list[str]) -> None:
    """Stage workspace-scoped files and commit them with a pathspec-scoped commit.

    Sealed contract — exactly one quoted commit message, optionally
    ``--approved`` and ``--include <path> [<path> ...]``. No ``-m``, no
    ``-F``, no ``--``, no bare pathspecs, no git flags: nothing is forwarded
    to git. Staging and the pathspec commit are internal implementation
    details.

    Scope authority: the final ``git commit`` runs with an explicit pathspec
    equal to (resolved workspace scope plus declared ``--include`` paths).
    Anything else in the index — staged by another session, by the human, or
    crash residue — is invisible to the pathspec and stays in the index for
    its owner. There is no env-var override; ``--include`` is the only way to
    extend scope, and the agent must name every path it claims.

    Caller paths:
    - Outside tmux: the wrapper passes through to plain git; this command is
      not in the picture.
    - Inside tmux: this command is the only sanctioned commit path.

    Safety primitives:
    1. Orchestrator restriction.
    2. main-branch lock serialises all ``_commit_under_lock`` bodies.
    3. ``telec code commit`` runs format + lint in-process before git commit.
    4. ``--approved`` is the Path A/B/C strategy gate; bare invocation prints
       the classification card and exits.
    5. The pathspec itself bounds the commit — no separate scope-enforcement
       gate is needed.

    Parsing rule: tokens are sorted into buckets left-to-right. ``--approved``
    is a boolean; ``--include`` switches subsequent non-flag tokens into the
    include bucket until the next flag; everything else is positional. The
    message must therefore precede ``--include`` (or be separated from it by
    ``--approved``).
    """
    approved = False
    includes: list[str] = []
    positionals: list[str] = []
    mode_include = False
    last_include_group_size = 0  # paths collected since the most recent --include
    saw_include = False
    for token in args:
        if token == "--approved":
            # An --approved (or any subsequent flag) closes the current
            # --include group; if that group was empty, error.
            if mode_include and last_include_group_size == 0:
                print(
                    "ERROR: --include requires at least one <path> operand.\n"
                    '  telec code commit --approved "<message>" --include <path> [<path> ...]',
                    file=sys.stderr,
                )
                raise SystemExit(2)
            approved = True
            mode_include = False
        elif token == "--include":
            if mode_include and last_include_group_size == 0:
                print(
                    "ERROR: --include requires at least one <path> operand before the next --include.\n"
                    '  telec code commit --approved "<message>" --include <path> [<path> ...]',
                    file=sys.stderr,
                )
                raise SystemExit(2)
            mode_include = True
            last_include_group_size = 0
            saw_include = True
        elif token.startswith("-"):
            print(
                f"ERROR: unknown flag: {token}\n"
                "Accepted flags: --approved, --include <path> [<path> ...].\n"
                "  telec code commit                                              # show A/B/C\n"
                '  telec code commit --approved "<message>"                       # commit scope\n'
                '  telec code commit --approved "<message>" --include <path> ...  # commit scope + extras',
                file=sys.stderr,
            )
            raise SystemExit(2)
        elif mode_include:
            includes.append(token)
            last_include_group_size += 1
        else:
            positionals.append(token)

    # End-of-args: if --include was the last token (or only followed by no
    # paths up to end), error too.
    if saw_include and mode_include and last_include_group_size == 0:
        print(
            "ERROR: --include requires at least one <path> operand.\n"
            '  telec code commit --approved "<message>" --include <path> [<path> ...]',
            file=sys.stderr,
        )
        raise SystemExit(2)

    if len(positionals) > 1:
        print(
            "ERROR: telec code commit accepts exactly one quoted message.\n"
            "If a path was consumed as part of the message, place --include after "
            "the message (or after --approved):\n"
            '  telec code commit --approved "<message>" --include <path> ...',
            file=sys.stderr,
        )
        raise SystemExit(2)

    message = positionals[0] if positionals else None
    system_role = get_system_role()
    project_root = resolve_git_root(resolve_invocation_cwd())

    # The absence of --approved is the trigger: surface guidance, never commit.
    # On main + non-integrator → Path A/B/C. Off main / integrator → short help.
    # An already-drafted message is fine to pass; it's just ignored until the
    # --approved re-run.
    if not approved:
        current_branch = _current_branch(project_root)
        if current_branch == "main" and system_role != "integrator":
            _print_commit_review_guidance()
            raise SystemExit(1)
        print(
            "telec code commit is the sealed canonical commit interface.\n"
            "Get human approval, then commit with:\n"
            '  telec code commit --approved "type(scope): subject"',
            file=sys.stderr,
        )
        raise SystemExit(2)

    # --approved → commit. Message required.
    if message is None:
        print(
            "ERROR: --approved requires a quoted commit message.\n"
            '  telec code commit --approved "type(scope): subject"',
            file=sys.stderr,
        )
        raise SystemExit(2)

    with main_branch_lock():
        _commit_under_lock(
            message=message,
            includes=includes,
            project_root=project_root,
            system_role=system_role,
        )


def _commit_under_lock(
    *,
    message: str,
    includes: list[str],
    project_root: Path,
    system_role: str | None,
) -> None:
    """Execute the commit sequence while holding the main-branch lock.

    Pathspec = resolved workspace scope plus declared ``--include`` paths.
    Anything else in the index is invisible to the pathspec and stays staged
    for its owner. Format and lint run in-process before the final
    ``git commit --no-verify``; the thin hook is only a raw-git backstop.
    """
    # Resolve any stale .git/index.lock before any git work. The check is
    # essentially free when no lock exists; when one does, it surfaces the
    # waiting state via the daemon log and self-heals orphan locks once
    # lsof confirms no holder (or the age ceiling is reached).
    wait_for_index_lock_clear(project_root)
    _check_commit_message(message, project_root)

    scope_resolution = resolve_workspace_scope_resolution(project_root)
    scope_paths = _commit_stage_paths(scope_resolution)

    # Single read-only status snapshot replaces five separate gitpython
    # probes. Shorter window between flock acquisition and the actual
    # commit means fewer chances for the Python parent to die holding
    # the index lock.
    snapshot = _working_tree_snapshot(project_root)

    # Untracked-NEW files in scope are NOT auto-included. The agent must
    # declare them explicitly via `telec code add` (which stages them) or
    # `--include` here. This catches the temp/scratch/debug-artifact failure
    # mode: an agent's tool calls touch incidental files that happen to land
    # in scope; the autodiscover model would commit them silently. Explicit
    # declaration is the safety net.
    untracked_unstaged_in_scope = sorted(p for p in scope_paths if p in snapshot.untracked and p not in snapshot.staged)

    auto_scope_paths = [p for p in scope_paths if not (p in snapshot.untracked and p not in snapshot.staged)]

    # Merge auto-scope plus includes, preserving order, deduped.
    seen: set[str] = set()
    pathspec: list[str] = []
    for path in auto_scope_paths:
        if path not in seen:
            seen.add(path)
            pathspec.append(path)
    for path in includes:
        if path not in seen:
            seen.add(path)
            pathspec.append(path)

    validated_pathspec = validate_commit_pathspec(pathspec, project_root)
    if len(validated_pathspec) != len(pathspec):
        print("ERROR: one or more commit paths were rejected by scoped path validation", file=sys.stderr)
        raise SystemExit(1)
    pathspec = validated_pathspec

    # Surface the auto-skip BEFORE the empty-pathspec exit so an agent whose
    # only scope is untracked-new sees the actionable reminder, not a
    # generic "nothing in scope" error.
    if untracked_unstaged_in_scope:
        print(
            f"Note: {len(untracked_unstaged_in_scope)} new file(s) in scope were not included in this commit:",
            file=sys.stderr,
        )
        for path in untracked_unstaged_in_scope:
            print(f"  {path}", file=sys.stderr)
        print(
            "\nIf intentional, declare them:\n"
            "  telec code add " + " ".join(untracked_unstaged_in_scope) + "  # then re-run commit\n"
            "  telec code commit --approved '<msg>' --include " + " ".join(untracked_unstaged_in_scope) + "\n"
            "If temp/scratch, leave them — they stay untracked.\n",
            file=sys.stderr,
        )

    if not pathspec:
        print(
            "Nothing in workspace scope to commit. Run `telec code changed` to "
            "see what telec would stage. For NEW files, declare them with "
            "`telec code add <path>` first, or pass `--include <path>` here.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Stage what git's data model genuinely requires before commit:
    #  - untracked files in our pathspec (must enter the index for git to know them)
    #  - unmerged files in our pathspec (must be marked resolved)
    # Modified-tracked files are committed straight from the working tree by
    # pathspec and need no staging.
    to_stage = [
        path
        for path in pathspec
        if (path in snapshot.untracked or path in snapshot.unmerged) and path not in snapshot.staged
    ]
    if to_stage:
        _stage_files(to_stage, project_root)

    # --include is a conscious force-include — the agent's final decision to put
    # these paths in the commit. We do not pre-reject it: a clean declared path is
    # a harmless no-op (git records nothing for it) and a non-existent one git
    # rejects naturally. Second-guessing an explicit include only produces
    # false-positives that block legitimate commits.

    # Partial-staging guard inside the pathspec. `git commit -- <path>`
    # records the working-tree version of <path>, not just the staged hunks.
    # If a file in our pathspec is partially staged (staged version + later
    # working-tree delta), the commit silently sweeps in the unstaged delta —
    # changes the agent never declared. Block the commit; the agent must
    # fully (re)stage the partial-staged file before retrying.
    overlap = snapshot.partial_staged & set(pathspec)
    if overlap:
        print("ERROR: partially staged files in commit pathspec:", file=sys.stderr)
        for path in sorted(overlap):
            print(f"  {path}", file=sys.stderr)
        print(
            "\n`git commit -- <path>` would commit the working-tree version, sweeping\n"
            "in unstaged hunks you did not declare. Fully (re)stage each file via the\n"
            "sealed recovery path (`telec code add` accepts partial-staged tracked\n"
            "files for exactly this case), then re-run telec code commit:\n"
            "  telec code add " + " ".join(sorted(overlap)),
            file=sys.stderr,
        )
        raise SystemExit(1)

    quality_paths = [path for path in pathspec if (project_root / path).exists()]
    if quality_paths:
        handle_format(quality_paths)
        handle_lint(quality_paths)

    # Auto-append the mandated trailer (idempotent) and commit via a message
    # file — robust against multi-line content, no shell arg-splitting.
    final_message = _with_trailer(message)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as msg_file:
        msg_file.write(final_message)
        msg_path = msg_file.name

    # Commit via gitpython (uses real binary, bypasses wrapper). Surface git's
    # own output so callers see the commit summary and any hook output.
    repo = Repo(str(project_root))
    try:
        _, stdout, stderr = repo.git.commit("-F", msg_path, "--no-verify", "--", *pathspec, with_extended_output=True)
    except GitCommandError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        os.unlink(msg_path)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    # Use actual committed file paths from git rather than the requested pathspec
    # strings, which may contain directory names or unexpanded globs that would
    # falsely match or miss doc patterns.
    try:
        committed_files = [p for p in repo.git.show("--name-only", "--format=", "HEAD").splitlines() if p]
    except GitCommandError:
        committed_files = list(pathspec)
    _record_commit_checkpoint_markers(project_root, committed_files)
    # system_role is retained on the signature for symmetry with prior gates;
    # the pathspec boundary makes a separate scope-enforcement step redundant.
    del system_role


def _record_commit_checkpoint_markers(project_root: Path, committed_files: list[str]) -> None:
    """Record checkpoint markers derived from the sealed commit."""
    session_id = get_session_id()
    if session_id:
        obligations = _commit_obligations_for_files(committed_files)
        try:
            record_commit_obligations(session_id, obligations)
        except OSError as exc:
            logger.warning(
                "Failed to record commit obligations checkpoint marker",
                session_id=session_id,
                error=str(exc),
            )
    committed_includes_code = any(not any(fnmatch(p, pat) for pat in _DOC_COMMIT_PATTERNS) for p in committed_files)
    if _current_branch(project_root) == "main" and committed_includes_code and session_id:
        record_authored_main_commit(session_id)


def _commit_obligations_for_files(files: list[str]) -> list[str]:
    """Return main-branch maintenance category names owed by committed files."""
    obligations: list[str] = []
    for category in sorted(CHECKPOINT_FILE_CATEGORIES, key=lambda item: item.precedence):
        if not category.main_only or not category.instruction:
            continue
        if any(_file_matches_commit_category(path, category) for path in files):
            obligations.append(category.name)
    return obligations


def _file_matches_commit_category(path: str, category: FileCategory) -> bool:
    """Return True when a committed path matches a checkpoint category."""
    if category.exclude_patterns and any(fnmatch(path, pattern) for pattern in category.exclude_patterns):
        return False
    return any(fnmatch(path, pattern) for pattern in category.include_patterns)


def _print_commit_review_guidance() -> None:
    """Print the post-commit review-routing guidance for a shared-main commit.

    The sealed contract makes ``--approved`` the single gate for any commit on
    main; the bare ``telec code commit`` invocation surfaces this guidance and
    exits — the agent commits with ``--approved`` and then routes the review by
    what the diff touched.
    """
    print(
        "Commit gate on main.\n"
        "\n"
        "Check scope first:\n"
        "  telec code changed\n"
        "\n"
        "New files require explicit inclusion:\n"
        "  telec code add <path> [<path> ...]\n"
        "  telec code commit --approved '<msg>' --include <path>\n"
        "\n"
        "Foreign staged files are excluded by pathspec. Do not unstage them.\n"
        "\n"
        "Commit it yourself with --approved '<msg>'. Never ask the human before committing.\n"
        "\n"
        "After committing, route the review by what the diff touched:\n"
        "   Functional code / tests -> judge whether review is warranted and say why; if you\n"
        "       recommend it, say so once, then dispatch the code review yourself if the\n"
        "       human stays silent 5 min.\n"
        "   Governed contract — doc snippets (docs/**) or agent artifacts (agents/**) -> required:\n"
        "       dispatch an independent doc-hygiene review (you may not review your own).\n"
        "   Neither functional code nor a governed contract -> no review.\n"
        "\n"
        "   Reuse the reviewer already open for this series — never spawn a second; else start one\n"
        "   (--mode fast for doc-hygiene, --mode med for code review):\n"
        "     telec sessions run --command /next-review-commits --args '<sha1,sha2,...>' --agent <agent> --mode <fast|med>\n"
        "     reuse open: telec sessions send <reviewer-session-id> 'review commits <sha1,sha2,...>'\n"
        "   Wait for REVIEW COMPLETE before reporting done.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _commit_stage_paths(scope_resolution: WorkspaceScopeResolution) -> list[str]:
    if scope_resolution.kind is WorkspaceScopeKind.WORKTREE:
        return [dirty.path for dirty in scope_resolution.dirty_paths]
    return list(scope_resolution.scoped_dirty_paths)


def _changed_paths(scope_resolution: WorkspaceScopeResolution) -> list[str]:
    if scope_resolution.kind is WorkspaceScopeKind.WORKTREE:
        return [dirty.path for dirty in scope_resolution.dirty_paths]
    return list(scope_resolution.scoped_existing_paths)


def _stage_files(files: list[str], project_root: Path) -> None:
    """Stage files via git add. Internal use only; agents are blocked at the
    wrapper from running ``git add`` directly. This call goes through
    gitpython → real git binary, bypassing the wrapper."""
    repo = Repo(str(project_root))
    repo.git.add("--", *files)


def validate_commit_pathspec(paths: list[str], project_root: Path) -> list[str]:
    """Validate commit pathspec entries before quality gates or git commit."""
    return validate_scoped_paths(paths, project_root)


def _check_commit_message(message: str, project_root: Path) -> None:
    """Run the commit message format gate before quality tooling."""
    _ = project_root
    subject = message.strip().splitlines()[0] if message.strip() else ""
    if not _COMMIT_MESSAGE_RE.match(subject):
        print("ERROR: commit message must follow Commitizen format: type(scope): subject", file=sys.stderr)
        raise SystemExit(1)


def _get_untracked_files(project_root: Path) -> list[str]:
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
    from the commit hot path (replaced by ``_working_tree_snapshot``);
    retained for test suites and external callers.
    """
    repo = Repo(str(project_root))
    diff_filter = "ACMRD" if include_deletions else "ACMR"
    output: str = repo.git.diff("--cached", "--name-only", f"--diff-filter={diff_filter}")
    return [f.strip() for f in output.strip().splitlines() if f.strip()]


def _get_unmerged_files(project_root: Path) -> list[str]:
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


def _dirty_paths(project_root: Path) -> set[str]:
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
    parts.update(_get_untracked_files(project_root))
    parts.update(_get_unmerged_files(project_root))
    return parts


@dataclass(frozen=True)
class _WorkingTreeSnapshot:
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


def _working_tree_snapshot(project_root: Path) -> _WorkingTreeSnapshot:
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
    return _WorkingTreeSnapshot(
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
    against ``_working_tree_snapshot``); retained for test suites and
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


def _current_branch(project_root: Path) -> str:
    """Return the current git branch name."""
    repo = Repo(str(project_root))
    branch: str = repo.git.rev_parse("--abbrev-ref", "HEAD")
    return branch.strip()

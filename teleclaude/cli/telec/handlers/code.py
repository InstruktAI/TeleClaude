"""CLI handlers for ``telec code`` namespace."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import OperationalError

from teleclaude.capabilities import resolve_capabilities
from teleclaude.checkpoint_model import load_checkpoint_model, triggered_action_ids
from teleclaude.cli.telec.handlers._code_git_state import (
    dirty_paths,
    get_unmerged_files,
    get_untracked_files,
    resolve_current_branch,
    working_tree_snapshot,
)
from teleclaude.cli.telec.handlers.quality import handle_format, handle_install, handle_lint, handle_test
from teleclaude.cli.telec.help import _usage
from teleclaude.commit_identity import CommitIdentityUnresolvable, compose_commit_footer, resolve_commit_identity
from teleclaude.constants import CHECKPOINT_BASE_AGENTS_BINDING, SlashCommand
from teleclaude.core.db import get_db
from teleclaude.core.next_machine.runtime.sessions import find_live_commit_reviewer_for_initiator
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_lock import main_branch_lock, wait_for_index_lock_clear
from teleclaude.hooks.checkpoint_flags import record_authored_main_commit, record_commit_obligations
from teleclaude.project_root import is_integration_worktree, resolve_git_root, resolve_invocation_cwd
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)
from teleclaude.session_identity import get_session_id, get_system_role

logger = get_logger(__name__)

_COMMIT_MESSAGE_RE = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+")
_DOC_LAYER_PATTERN = "docs/**"
_STANDALONE_PROSE_PATTERNS = ("*.md", "*.txt", "*.rst")
_NON_CODE_DOCUMENTATION_PATTERNS = (_DOC_LAYER_PATTERN, *_STANDALONE_PROSE_PATTERNS)
# The doc layer is authored at prepare on `main` and folded at integration; a slug
# worktree commit must never touch it. Deliberately narrower than
# `_NON_CODE_DOCUMENTATION_PATTERNS` so the guard only refuses the doc layer
# itself, not incidental prose elsewhere in the tree.
_CODE_NAMESPACE = "code"
_CODE_CAPABILITY_REQUIRED = "ERROR: telec code {command} requires the code capability"
_COMMIT_CAPABILITY_REQUIRED = "ERROR: telec code {command} requires the code or docs capability"


class CodeSubcommand(StrEnum):
    """Closed command vocabulary for capability routing."""

    LINT = "lint"
    TEST = "test"
    FORMAT = "format"
    INSTALL = "install"
    COMMIT = "commit"
    CHANGED = "changed"
    ADD = "add"
    BLUEPRINT = "blueprint"


_CODE_CAPABILITY_SUBCOMMANDS = frozenset(
    {
        CodeSubcommand.LINT,
        CodeSubcommand.TEST,
        CodeSubcommand.FORMAT,
        CodeSubcommand.INSTALL,
        CodeSubcommand.BLUEPRINT,
    }
)
_COMMIT_SUBCOMMANDS = frozenset({CodeSubcommand.COMMIT, CodeSubcommand.CHANGED, CodeSubcommand.ADD})


def handle_code(args: list[str]) -> None:
    """Route ``telec code <subcommand>`` to the correct handler."""
    if not args:
        print(_usage(_CODE_NAMESPACE))
        return
    try:
        sub = CodeSubcommand(args[0])
    except ValueError:
        print(_usage(_CODE_NAMESPACE))
        return
    rest = args[1:]
    _require_code_capability(sub)
    if sub is CodeSubcommand.LINT:
        handle_lint(rest)
    elif sub is CodeSubcommand.TEST:
        handle_test(rest)
    elif sub is CodeSubcommand.FORMAT:
        handle_format(rest)
    elif sub is CodeSubcommand.INSTALL:
        handle_install(rest)
    elif sub is CodeSubcommand.COMMIT:
        handle_code_commit(rest)
    elif sub is CodeSubcommand.CHANGED:
        handle_code_changed(rest)
    elif sub is CodeSubcommand.ADD:
        handle_code_add(rest)
    elif sub is CodeSubcommand.BLUEPRINT:
        from teleclaude.cli.telec.handlers.blueprint import handle_code_blueprint  # noqa: PLC0415

        handle_code_blueprint(rest)


def _require_code_capability(command: CodeSubcommand) -> None:
    """Refuse commands whose owning project capability is unsubscribed."""
    project_root = resolve_git_root(resolve_invocation_cwd())
    capabilities = resolve_capabilities(project_root)
    if command in _CODE_CAPABILITY_SUBCOMMANDS and not capabilities.code:
        print(_CODE_CAPABILITY_REQUIRED.format(command=command.value), file=sys.stderr)
        raise SystemExit(1)
    if command in _COMMIT_SUBCOMMANDS and not capabilities.commit_enabled:
        print(_COMMIT_CAPABILITY_REQUIRED.format(command=command.value), file=sys.stderr)
        raise SystemExit(1)


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
    untracked = set(get_untracked_files(project_root))
    unmerged = set(get_unmerged_files(project_root))
    dirty = dirty_paths(project_root)
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
    ``--approved``, ``--human-involved``, ``--include <path> [<path> ...]``,
    and ``--only <path> [<path> ...]``. No ``-m``, no
    ``-F``, no ``--``, no bare pathspecs, no git flags: nothing is forwarded
    to git. Staging and the pathspec commit are internal implementation
    details.

    Scope authority: the final ``git commit`` runs with an explicit pathspec
    equal to (resolved workspace scope plus declared ``--include`` paths), or
    exactly declared ``--only`` paths when explicit subset mode is used.
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
    4. ``--approved`` is the commit gate; bare invocation prints the
       review-routing guidance (exit 0) and never commits.
    5. The pathspec itself bounds the commit — no separate scope-enforcement
       gate is needed.

    Parsing rule: tokens are sorted into buckets left-to-right. ``--approved``
    is a boolean; ``--include``/``--only`` switch subsequent non-flag tokens
    into their path bucket until the next flag; everything else is positional.
    The message must therefore precede path flags (or be separated from them
    by ``--approved``).
    """
    approved = False
    human_involved = False
    includes: list[str] = []
    only: list[str] = []
    positionals: list[str] = []
    path_mode: str | None = None
    last_path_group_size = 0  # paths collected since the most recent path flag
    saw_path_flag: str | None = None
    for token in args:
        if token == "--approved":
            # An --approved (or any subsequent flag) closes the current
            # path group; if that group was empty, error.
            if path_mode is not None and last_path_group_size == 0:
                print(
                    f"ERROR: --{path_mode} requires at least one <path> operand.\n"
                    f'  telec code commit --approved "<message>" --{path_mode} <path> [<path> ...]',
                    file=sys.stderr,
                )
                raise SystemExit(2)
            approved = True
            path_mode = None
        elif token == "--human-involved":
            if path_mode is not None and last_path_group_size == 0:
                print(
                    f"ERROR: --{path_mode} requires at least one <path> operand.\n"
                    f'  telec code commit --approved "<message>" --{path_mode} <path> [<path> ...]',
                    file=sys.stderr,
                )
                raise SystemExit(2)
            human_involved = True
            path_mode = None
        elif token in {"--include", "--only"}:
            if path_mode is not None and last_path_group_size == 0:
                print(
                    f"ERROR: --{path_mode} requires at least one <path> operand before the next path flag.\n"
                    f'  telec code commit --approved "<message>" --{path_mode} <path> [<path> ...]',
                    file=sys.stderr,
                )
                raise SystemExit(2)
            path_mode = token.removeprefix("--")
            last_path_group_size = 0
            saw_path_flag = path_mode
        elif token.startswith("-"):
            print(
                f"ERROR: unknown flag: {token}\n"
                "Accepted flags: --approved, --human-involved, --include <path> [<path> ...], "
                "--only <path> [<path> ...].\n"
                "  telec code commit                                              # show the gate\n"
                '  telec code commit --approved "<message>"                       # commit scope\n'
                '  telec code commit --approved "<message>" --include <path> ...  # commit scope + extras\n'
                '  telec code commit --approved "<message>" --only <path> ...     # commit exactly these paths',
                file=sys.stderr,
            )
            raise SystemExit(2)
        elif path_mode == "include":
            includes.append(token)
            last_path_group_size += 1
        elif path_mode == "only":
            only.append(token)
            last_path_group_size += 1
        else:
            positionals.append(token)

    # End-of-args: if a path flag was the last token (or only followed by no
    # paths up to end), error too.
    if saw_path_flag is not None and path_mode is not None and last_path_group_size == 0:
        print(
            f"ERROR: --{path_mode} requires at least one <path> operand.\n"
            f'  telec code commit --approved "<message>" --{path_mode} <path> [<path> ...]',
            file=sys.stderr,
        )
        raise SystemExit(2)

    if includes and only:
        print(
            "ERROR: --only cannot be combined with --include.\n"
            '  telec code commit --approved "<message>" --only <path> [<path> ...]',
            file=sys.stderr,
        )
        raise SystemExit(2)

    if len(positionals) > 1:
        print(
            "ERROR: telec code commit accepts exactly one quoted message.\n"
            "If a path was consumed as part of the message, place path flags after "
            "the message (or after --approved):\n"
            '  telec code commit --approved "<message>" --only <path> ...',
            file=sys.stderr,
        )
        raise SystemExit(2)

    message = positionals[0] if positionals else None
    system_role = get_system_role()
    project_root = resolve_git_root(resolve_invocation_cwd())

    # The absence of --approved is the trigger: surface guidance, never commit.
    # On main + non-integrator → commit-first review-routing gate. Off main / integrator → short help.
    # Bare invocation (no message) is discovery — serving the menu is the
    # successful outcome, so exit 0. A message without --approved means the agent
    # meant to commit and skipped the gate: a real miss, so exit non-zero to stop
    # a wrapper from reading the no-op as success.
    if not approved:
        forgot_gate = message is not None
        current_branch = resolve_current_branch(project_root)
        if current_branch == "main" and system_role != "integrator":
            _print_commit_review_guidance(project_root)
            raise SystemExit(1 if forgot_gate else 0)
        print(
            "telec code commit is the sealed canonical commit interface.\n"
            "Use --approved to acknowledge the agent-owned commit gate:\n"
            '  telec code commit --approved "type(scope): subject"',
            file=sys.stderr,
        )
        raise SystemExit(2 if forgot_gate else 0)

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
            only=only or None,
            human_involved=human_involved,
        )


def _commit_under_lock(
    *,
    message: str,
    includes: list[str],
    project_root: Path,
    system_role: str | None,
    only: list[str] | None = None,
    human_involved: bool = False,
) -> None:
    """Execute the commit sequence while holding the main-branch lock.

    Pathspec = resolved workspace scope plus declared ``--include`` paths, or
    exactly declared ``--only`` paths when explicit subset mode is used.
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
    if only is not None and includes:
        print("ERROR: --only cannot be combined with --include.", file=sys.stderr)
        raise SystemExit(2)

    repo = Repo(str(project_root))
    if _merge_head_path(repo).exists():
        _commit_active_merge(repo, message, project_root=project_root, human_involved=human_involved)
        del system_role
        return

    scope_resolution = resolve_workspace_scope_resolution(project_root)
    scope_paths = _commit_stage_paths(scope_resolution)

    # Single read-only status snapshot replaces five separate gitpython
    # probes. Shorter window between flock acquisition and the actual
    # commit means fewer chances for the Python parent to die holding
    # the index lock.
    snapshot = working_tree_snapshot(project_root)

    # Untracked-NEW files in scope are NOT auto-included. The agent must
    # declare them explicitly via `telec code add` (which stages them) or
    # `--include` here. This catches the temp/scratch/debug-artifact failure
    # mode: an agent's tool calls touch incidental files that happen to land
    # in scope; the autodiscover model would commit them silently. Explicit
    # declaration is the safety net.
    untracked_unstaged_in_scope = sorted(p for p in scope_paths if p in snapshot.untracked and p not in snapshot.staged)

    auto_scope_paths = [p for p in scope_paths if not (p in snapshot.untracked and p not in snapshot.staged)]

    # Compose the pathspec, preserving order, deduped. Default mode is
    # workspace scope + extras; --only is the explicit split-commit primitive.
    seen: set[str] = set()
    pathspec: list[str] = []
    base_paths = only if only is not None else auto_scope_paths
    extra_paths = [] if only is not None else includes
    for path in base_paths:
        if path not in seen:
            seen.add(path)
            pathspec.append(path)
    for path in extra_paths:
        if path not in seen:
            seen.add(path)
            pathspec.append(path)

    validated_pathspec = validate_commit_pathspec(pathspec, project_root)
    if len(validated_pathspec) != len(pathspec):
        print("ERROR: one or more commit paths were rejected by scoped path validation", file=sys.stderr)
        raise SystemExit(1)
    pathspec = validated_pathspec

    # Phase separation: the doc layer is authored at prepare on `main` and
    # folded at integration, so the work phase must execute a frozen contract.
    # Refuse before any staging/format/lint/commit runs. The integration
    # worktree is excluded because the integrator's fold step legitimately
    # commits docs/** there.
    _refuse_doc_layer_in_slug_worktree(scope_resolution, project_root, pathspec)

    # Surface the auto-skip BEFORE the empty-pathspec exit so an agent whose
    # only scope is untracked-new sees the actionable reminder, not a
    # generic "nothing in scope" error.
    if only is None and untracked_unstaged_in_scope:
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

    # Compose the mandated footer (author identity + branding + session +
    # involvement, never a message scan) and commit via a message file —
    # robust against multi-line content, no shell arg-splitting. Commit via
    # gitpython (uses real binary, bypasses wrapper). Surface git's own
    # output so callers see the commit summary and any hook output.
    stdout, stderr = _commit_repo_with_message(
        repo,
        message,
        commit_args=("-F", "{message_file}", "--no-verify", "--", *pathspec),
        human_involved=human_involved,
    )
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


def _commit_active_merge(repo: Repo, message: str, *, project_root: Path, human_involved: bool = False) -> None:
    """Close an active merge as a full-index commit."""
    snapshot = working_tree_snapshot(project_root)
    if snapshot.unmerged:
        print("ERROR: unresolved paths remain during merge commit:", file=sys.stderr)
        for path in sorted(snapshot.unmerged):
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(1)

    quality_paths = _merge_quality_paths(repo, project_root)
    if quality_paths:
        handle_format(quality_paths)
        handle_lint(quality_paths)

    stdout, stderr = _commit_repo_with_message(
        repo,
        message,
        commit_args=("-F", "{message_file}", "--no-verify"),
        human_involved=human_involved,
    )
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    try:
        committed_files = [p for p in repo.git.show("--name-only", "--format=", "HEAD").splitlines() if p]
    except GitCommandError:
        committed_files = quality_paths
    _record_commit_checkpoint_markers(project_root, committed_files)


def _commit_repo_with_message(
    repo: Repo,
    message: str,
    *,
    commit_args: tuple[str, ...],
    human_involved: bool = False,
) -> tuple[str, str]:
    """Commit with the resolved author identity and mandated footer.

    Resolves the authoring identity fresh for every commit — an agent session
    stamps its own bot identity as ``--author``; a genuine terminal-login human
    stamps nothing (git's own ambient identity is already theirs); anything
    else is a resolution failure and stops the commit rather than silently
    misattributing it.
    """
    try:
        git_identity, session_id = resolve_commit_identity()
    except CommitIdentityUnresolvable as exc:
        raise SystemExit(str(exc)) from exc

    final_message = compose_commit_footer(message, session_id=session_id, human_involved=human_involved)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as msg_file:
        msg_file.write(final_message)
        msg_path = msg_file.name

    args = tuple(msg_path if arg == "{message_file}" else arg for arg in commit_args)
    if git_identity is not None:
        args = ("--author", git_identity, *args)
    try:
        _, stdout, stderr = repo.git.commit(*args, with_extended_output=True)
    except GitCommandError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        os.unlink(msg_path)
    return stdout, stderr


def _merge_head_path(repo: Repo) -> Path:
    """Return the gitdir-local MERGE_HEAD path."""
    return Path(repo.git_dir) / "MERGE_HEAD"


def _merge_quality_paths(repo: Repo, project_root: Path) -> list[str]:
    """Return existing files changed by the incoming merge side."""
    merge_base = repo.git.merge_base("HEAD", "MERGE_HEAD").strip()
    output = repo.git.diff("--name-only", f"{merge_base}..MERGE_HEAD")
    paths = [line.strip() for line in output.splitlines() if line.strip()]
    return [path for path in paths if (project_root / path).exists()]


def _record_commit_checkpoint_markers(project_root: Path, committed_files: list[str]) -> None:
    """Record checkpoint markers derived from the sealed commit."""
    session_id = get_session_id()
    current_branch = resolve_current_branch(project_root)
    if session_id and current_branch == "main":
        obligations = _commit_obligations_for_files(committed_files, project_root)
        try:
            record_commit_obligations(session_id, obligations)
        except OSError as exc:
            logger.warning(
                "Failed to record commit obligations checkpoint marker",
                session_id=session_id,
                error=str(exc),
            )
    committed_includes_code = any(
        not any(fnmatch(path, pattern) for pattern in _NON_CODE_DOCUMENTATION_PATTERNS) for path in committed_files
    )
    if current_branch == "main" and committed_includes_code and session_id:
        record_authored_main_commit(session_id)


def _commit_obligations_for_files(files: list[str], project_root: Path) -> list[str]:
    """Return main-only maintenance action ids owed by committed files.

    Resolves through the same merged checkpoint model and single matcher the hook
    engine uses, so a committed path owes the equivalent action in both consumers.
    """
    model = load_checkpoint_model(str(project_root))
    owed = triggered_action_ids(files, model)
    main_only = [action_id for action_id in owed if action_id in model.actions and model.actions[action_id].main_only]
    return sorted(main_only, key=lambda action_id: (model.actions[action_id].precedence, action_id))


async def _commit_reviewer_session_id_async(project_root: Path, initiator_session_id: str) -> str | None:
    """Resolve the live commit-review session open for this project and driver."""
    runtime_db = await get_db()
    return await find_live_commit_reviewer_for_initiator(
        runtime_db, project_root, initiator_session_id, SlashCommand.NEXT_REVIEW_COMMITS.value
    )


def _resolve_open_commit_reviewer(project_root: Path) -> str | None:
    """Resolve the concrete session id of an open commit reviewer for this driver, or None.

    Advisory only — this backs a printed hint, never a gate. Any resolution
    failure (no session identity, no runtime, an unreachable database) yields
    ``None`` so the caller falls back to the start-only form; resolving this
    hint can never become a new way for ``telec code commit`` to fail.
    """
    initiator_session_id = get_session_id()
    if not initiator_session_id:
        return None
    try:
        return asyncio.run(_commit_reviewer_session_id_async(project_root, initiator_session_id))
    except (OperationalError, OSError, RuntimeError):
        return None


def _print_commit_review_guidance(project_root: Path) -> None:
    """Print the active commit-gate continuation instructions for shared main.

    The sealed contract makes ``--approved`` the single gate for any commit on
    main; the bare ``telec code commit`` invocation enters the commit gate. The
    caller owns the exit code, but the printed surface is a continuation
    instruction: commit or reach a concrete blocker before reporting done.
    """
    reviewer_session_id = _resolve_open_commit_reviewer(project_root)
    documentation_patterns = ", ".join(_NON_CODE_DOCUMENTATION_PATTERNS)
    standalone_prose_patterns = ", ".join(_STANDALONE_PROSE_PATTERNS)
    agent_artifact_patterns = ", ".join(CHECKPOINT_BASE_AGENTS_BINDING.scope.include)
    if reviewer_session_id:
        review_dispatch = (
            "   Reuse the reviewer already open for this series — never spawn a second; else start one\n"
            "   (--mode fast for doc-hygiene, --mode med for code review):\n"
            "     telec sessions run --command /next-review-commits --args '<sha1,sha2,...>' --agent <agent> --mode <fast|med>\n"
            f"     reuse open: telec sessions send {reviewer_session_id} 'review commits <sha1,sha2,...>'\n"
        )
    else:
        review_dispatch = (
            "   Start the reviewer for this series (--mode fast for doc-hygiene, --mode med for code review):\n"
            "     telec sessions run --command /next-review-commits --args '<sha1,sha2,...>' --agent <agent> --mode <fast|med>\n"
        )
    print(
        "COMMIT GATE ACTIVE — CONTINUE NOW\n"
        "\n"
        "This output is not informational. Follow it until one terminal state:\n"
        "- a commit is created and required review routing is completed or started as instructed; or\n"
        "- a concrete blocker is reached.\n"
        "\n"
        "Required next steps:\n"
        "1. Inspect scope:\n"
        "  telec code changed\n"
        "   Treat that output as your authoritative ownership scope.\n"
        "   Do not use raw git status to override TeleClaude scope.\n"
        "\n"
        "2. Commit the intended scoped work yourself. Never ask the human before committing.\n"
        "   If this scope contains multiple separable intents, make multiple commits with --only:\n"
        "  telec code commit --approved '<msg>' --only <path> [<path> ...]\n"
        "   Then rerun `telec code changed` until the scoped work is clean.\n"
        "   New files require explicit inclusion:\n"
        "  telec code add <path> [<path> ...]\n"
        "  telec code commit --approved '<msg>' --include <path>\n"
        "\n"
        "   Foreign staged files are excluded by pathspec. Do not unstage them.\n"
        "\n"
        "3. After committing, route the review by what the diff touched:\n"
        "   Remediation only — the diff just applies an open review's findings and adds no\n"
        "       new reviewable surface -> send it back to that same reviewer to confirm; do\n"
        "       not offer a fresh review. Its APPROVE is terminal.\n"
        f"   Any path matched by neither documentation ({documentation_patterns}) nor agent artifacts\n"
        f"       ({agent_artifact_patterns}) ->\n"
        "       dispatch independent code review automatically.\n"
        f"   Documentation snippets ({_DOC_LAYER_PATTERN}) or agent artifacts ({agent_artifact_patterns}) -> required:\n"
        "       dispatch an independent doc-hygiene review (you may not review your own).\n"
        f"   Standalone descriptive prose ({standalone_prose_patterns}) outside {_DOC_LAYER_PATTERN} -> no\n"
        "       independent review; directive text follows the functional-code review path.\n"
        "\n"
        f"{review_dispatch}"
        "   Wait for REVIEW COMPLETE before reporting done. REQUEST CHANGES remains with\n"
        "   you for evidence-based rejection or in-scope remediation and re-review; carry\n"
        "   only a genuine human-owned decision, unresolved contract deadlock, or safety gate.\n",
        file=sys.stderr,
    )


def _refuse_doc_layer_in_slug_worktree(
    scope_resolution: WorkspaceScopeResolution,
    project_root: Path,
    pathspec: list[str],
) -> None:
    """Refuse a commit whose pathspec touches docs/** from a slug worktree.

    Exits before any staging/format/lint/commit runs. The integration worktree
    is excluded because the integrator's fold step legitimately commits
    docs/** there.
    """
    if scope_resolution.kind is not WorkspaceScopeKind.WORKTREE or is_integration_worktree(project_root):
        return
    doc_layer_paths = [path for path in pathspec if fnmatch(path, _DOC_LAYER_PATTERN)]
    if not doc_layer_paths:
        return
    print("ERROR: doc-layer paths cannot be committed from a slug worktree:", file=sys.stderr)
    for path in doc_layer_paths:
        print(f"  {path}", file=sys.stderr)
    print(
        "\nThe doc layer is authored at prepare on main and folded at integration; "
        "the work phase executes a frozen contract. If a doc need surfaced mid-build, "
        "kick back instead of editing docs/** here:\n"
        '  telec todo stamp <slug> --kickback --reason "<why the plan cannot be built>"',
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

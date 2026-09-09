"""CLI handlers for ``telec code`` namespace."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import OperationalError

from teleclaude.capabilities import Capabilities, TierPermissions, resolve_capabilities, resolve_tier_permissions
from teleclaude.checkpoint_model import main_only_action_ids_for_files
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._code_git_state import (
    dirty_paths,
    get_unmerged_files,
    get_untracked_files,
    resolve_current_branch,
    working_tree_snapshot,
)
from teleclaude.cli.telec.handlers._code_pre_commit import handle_code_pre_commit
from teleclaude.cli.telec.handlers.quality import handle_format, handle_install, handle_lint, handle_test
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import CODE_CHANGED, CODE_COMMIT
from teleclaude.commit_identity import CommitIdentityUnresolvable, compose_commit_footer, resolve_commit_identity
from teleclaude.constants import CHECKPOINT_BASE_AGENTS_BINDING, SlashCommand
from teleclaude.core.db import get_db
from teleclaude.core.dirty_path_owners import resolve_dirty_path_owners
from teleclaude.core.next_machine.runtime.sessions import list_live_commit_reviewers_for_initiator
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_lock import main_branch_lock, wait_for_index_lock_clear
from teleclaude.hooks.checkpoint_flags import record_authored_main_commit, record_commit_obligations
from teleclaude.project_root import (
    DOC_LAYER_PATTERN,
    forbidden_slug_worktree_doc_paths,
    resolve_invocation_roots,
)
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    resolve_workspace_scope_resolution,
    validate_context_paths,
    validate_scoped_paths,
)
from teleclaude.session_identity import get_session_id, get_system_role

logger = get_logger(__name__)
_COMMIT_MESSAGE_RE = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+")
_STANDALONE_PROSE_PATTERNS = ("*.md", "*.txt", "*.rst")
_NON_CODE_DOCUMENTATION_PATTERNS = (DOC_LAYER_PATTERN, *_STANDALONE_PROSE_PATTERNS)
# The doc layer is authored at prepare on `main` and folded at integration; a slug
# worktree commit must never touch it. Deliberately narrower than
# `_NON_CODE_DOCUMENTATION_PATTERNS` so the guard only refuses the doc layer
# itself, not incidental prose elsewhere in the tree.
_CODE_NAMESPACE = "code"
_CODE_CAPABILITY_REQUIRED = "ERROR: telec code {command} requires the code capability"
_COMMIT_CAPABILITY_REQUIRED = "ERROR: telec code {command} requires the code or docs capability"
_OWNERS_USAGE = "Usage: telec code owners <path> [<path> ...]"
_OWNERS_UNKNOWN_FLAG = "ERROR: unknown flag: {flag}"
_OWNERS_ERROR = "ERROR: {error}"
_OWNERS_UNDETERMINED_WARNING = "WARNING: {count} captured session(s) had undetermined attribution; do not revert null-owned paths from this result."


@dataclass(frozen=True)
class InvocationState:
    """Resolved roots and capability declaration for one code invocation."""

    context_root: Path | None
    repository_root: Path
    tier_permissions: TierPermissions | None

    @property
    def project_root(self) -> Path:
        """Return the repository root retained by existing code paths."""
        return self.repository_root

    @property
    def capabilities(self) -> Capabilities:
        """Return subscriptions from the acting tier, or legacy repository state."""
        if self.tier_permissions is not None:
            return self.tier_permissions.project_subscriptions
        return resolve_capabilities(self.repository_root)

    @property
    def is_invocation_context(self) -> bool:
        """Return whether this invocation has a declared acting context."""
        return self.tier_permissions is not None and self.tier_permissions.invocation_context

    @property
    def is_non_project_invocation_context(self) -> bool:
        """Return whether the acting context is a non-project tier root."""
        return self.is_invocation_context and not self.capabilities.is_target


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
    OWNERS = "owners"
    PRE_COMMIT = "pre-commit"


_CODE_CAPABILITY_SUBCOMMANDS = frozenset(
    {
        CodeSubcommand.LINT,
        CodeSubcommand.TEST,
        CodeSubcommand.FORMAT,
        CodeSubcommand.INSTALL,
        CodeSubcommand.BLUEPRINT,
        CodeSubcommand.OWNERS,
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
    if sub is CodeSubcommand.PRE_COMMIT:
        handle_code_pre_commit(rest)
        return
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
    elif sub is CodeSubcommand.OWNERS:
        handle_code_owners(rest)


def _require_code_capability(command: CodeSubcommand) -> None:
    """Refuse commands whose owning project capability is unsubscribed."""
    state = _resolve_invocation_state()
    if command in _CODE_CAPABILITY_SUBCOMMANDS and not state.capabilities.code:
        print(_CODE_CAPABILITY_REQUIRED.format(command=command.value), file=sys.stderr)
        raise SystemExit(1)
    if command in _COMMIT_SUBCOMMANDS and not (
        state.is_non_project_invocation_context or state.capabilities.commit_enabled
    ):
        print(_COMMIT_CAPABILITY_REQUIRED.format(command=command.value), file=sys.stderr)
        raise SystemExit(1)


def _resolve_invocation_state() -> InvocationState:
    """Resolve the acting context and containing repository for one command."""
    roots = resolve_invocation_roots()
    permissions = resolve_tier_permissions(roots.context_root) if roots.context_root is not None else None
    return InvocationState(
        context_root=roots.context_root,
        repository_root=roots.repository_root,
        tier_permissions=permissions,
    )


def handle_code_owners(args: list[str]) -> None:
    """Print the strict live-session ownership view for supplied dirty paths."""
    if not args:
        print(_OWNERS_USAGE, file=sys.stderr)
        raise SystemExit(2)
    for argument in args:
        if argument.startswith("-"):
            print(_OWNERS_UNKNOWN_FLAG.format(flag=argument), file=sys.stderr)
            print(_OWNERS_USAGE, file=sys.stderr)
            raise SystemExit(2)
    state = _resolve_invocation_state()
    project_root = state.project_root
    try:
        result = asyncio.run(resolve_dirty_path_owners(project_root, args))
    except Exception as exc:
        print(_OWNERS_ERROR.format(error=exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.as_json()))
    if result.undetermined_session_count:
        print(
            _OWNERS_UNDETERMINED_WARNING.format(count=result.undetermined_session_count),
            file=sys.stderr,
        )


def handle_code_add(args: list[str]) -> None:
    """Declare files for the next commit and stage only when Git requires it.

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

    Every successful call declares its paths to session-scoping. Modified-tracked
    files that are NOT partial-staged therefore succeed without index mutation.
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
            "Declares paths for the next `telec code commit`; NEW files are also staged.\n"
            "Modified tracked files are declared without staging because pathspec commits\n"
            "them directly from the working tree.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    state = _resolve_invocation_state()
    project_root = state.project_root
    validated_positionals = validate_context_paths(positionals, project_root, state.context_root)
    if len(validated_positionals) != len(positionals):
        print("ERROR: one or more paths were rejected outside the invocation context", file=sys.stderr)
        raise SystemExit(1)
    positionals = validated_positionals
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
        # Modified tracked paths are declarations; pathspec commit needs no index mutation.
        print(
            "Declared already tracked + modified path(s); no staging needed (the pathspec\n"
            "commit takes them straight from the working tree):\n  " + "\n  ".join(already_tracked),
            file=sys.stderr,
        )

    if stageable:
        with main_branch_lock():
            wait_for_index_lock_clear(project_root)
            _stage_files(stageable, project_root)
        # "Staged" without "new" — this command also handles unmerged and
        # partial-staged tracked recoveries, so the diagnostic stays neutral.
        print(f"Staged {len(stageable)} file(s):")
        for path in stageable:
            print(f"  {path}")


def handle_code_changed(args: list[str]) -> None:
    """List workspace-scoped changed files."""
    parsed = parse_command_args(CODE_CHANGED, args)
    if parsed.positionals:
        print("ERROR: changed accepts paths only after --include or --only", file=sys.stderr)
        raise SystemExit(2)
    includes = list(parsed.values(F.FLAG_CODE_CHANGED_INCLUDE))
    only = list(parsed.values(F.FLAG_CODE_CHANGED_ONLY))
    if includes and only:
        print("ERROR: --only cannot be combined with --include.", file=sys.stderr)
        raise SystemExit(2)

    state = _resolve_invocation_state()
    project_root = state.project_root
    scope_resolution = resolve_workspace_scope_resolution(project_root, context_root=state.context_root)
    includes = _resolve_context_payload_paths(includes, project_root, state.context_root)
    only = _resolve_context_payload_paths(only, project_root, state.context_root)
    files = _display_context_paths(only, project_root, state.context_root) if only else _changed_paths(scope_resolution)
    files = [*files, *_display_context_paths(includes, project_root, state.context_root)]
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

    Parsing rule: option recognition is declaration-driven (see
    ``teleclaude.cli.telec.flags.FLAG_COMMIT_INCLUDE``/``FLAG_COMMIT_ONLY``,
    both GREEDY). A GREEDY flag consumes every following token up to the next
    dash-leading token, at least one; ``--include``/``--only`` therefore stop
    collecting paths at the next flag (including ``--approved`` or
    ``--human-involved``) and the parser itself raises a missing-value error
    when no path follows. The message must precede any path flag, or be
    separated from it by ``--approved``, since a GREEDY flag would otherwise
    swallow it as a path.
    """
    parsed = parse_command_args(CODE_COMMIT, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(
            "ERROR: telec code commit accepts exactly one quoted message.\n"
            "If a path was consumed as part of the message, place path flags after "
            "the message (or after --approved):\n"
            '  telec code commit --approved "<message>" --only <path> ...',
            file=sys.stderr,
        )
        raise SystemExit(2)

    approved = parsed.has(F.FLAG_COMMIT_APPROVED)
    human_involved = parsed.has(F.FLAG_HUMAN_INVOLVED_COMMIT)
    includes = list(parsed.values(F.FLAG_COMMIT_INCLUDE))
    only = list(parsed.values(F.FLAG_COMMIT_ONLY))

    if includes and only:
        print(
            "ERROR: --only cannot be combined with --include.\n"
            '  telec code commit --approved "<message>" --only <path> [<path> ...]',
            file=sys.stderr,
        )
        raise SystemExit(2)

    message = positionals[0] if positionals else None
    system_role = get_system_role()
    state = _resolve_invocation_state()
    project_root = state.project_root
    includes = _resolve_context_payload_paths(includes, project_root, state.context_root)
    only = _resolve_context_payload_paths(only, project_root, state.context_root)

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
            context_root=state.context_root,
            run_quality_gates=state.capabilities.commit_enabled,
            enforce_context_bound=state.is_non_project_invocation_context,
            system_role=system_role,
            only=only or None,
            human_involved=human_involved,
        )


def _commit_under_lock(
    *,
    message: str,
    includes: list[str],
    project_root: Path,
    context_root: Path | None,
    run_quality_gates: bool,
    enforce_context_bound: bool,
    system_role: str | None,
    only: list[str] | None = None,
    human_involved: bool = False,
) -> None:
    """Commit the resolved pathspec while holding the main-branch lock."""
    # Clear stale index locks before work, minimizing the flock window.
    wait_for_index_lock_clear(project_root)
    _check_commit_message(message, project_root)
    if only is not None and includes:
        print("ERROR: --only cannot be combined with --include.", file=sys.stderr)
        raise SystemExit(2)

    repo = Repo(str(project_root))
    if _merge_head_path(repo).exists():
        _commit_active_merge(
            repo,
            message,
            project_root=project_root,
            context_root=context_root,
            run_quality_gates=run_quality_gates,
            enforce_context_bound=enforce_context_bound,
            human_involved=human_involved,
        )
        del system_role
        return

    scope_resolution = resolve_workspace_scope_resolution(project_root, context_root=context_root)
    scope_paths = _commit_stage_paths(scope_resolution)

    # One snapshot replaces five Git probes and shortens the lock window.
    snapshot = working_tree_snapshot(project_root)

    # New files need explicit declaration so scratch output is never swept in.
    untracked_unstaged_in_scope = sorted(p for p in scope_paths if p in snapshot.untracked and p not in snapshot.staged)

    auto_scope_paths = [p for p in scope_paths if not (p in snapshot.untracked and p not in snapshot.staged)]

    # Preserve declaration order while deduplicating the final Git pathspec.
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

    # Docs are frozen during work; only integration may fold docs/**.
    _refuse_doc_layer_in_slug_worktree(scope_resolution, project_root, pathspec)

    # Explain skipped new files before an empty-scope failure hides recovery.
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

    # Only untracked/unmerged entries need staging; tracked paths use pathspec.
    to_stage = [
        path
        for path in pathspec
        if (path in snapshot.untracked or path in snapshot.unmerged) and path not in snapshot.staged
    ]

    # A declared --include/--only path must contribute a change git will
    # record, or a directory beneath which one does. Checked before staging so
    # a refusal leaves the index untouched. `snapshot.dirty` is deliberately
    # excluded from the admissible set: it includes plain untracked files, so
    # an untracked-and-unstaged directory would pass via the prefix clause
    # without anything of it ever reaching git's pathspec match.
    declared_paths = only if only is not None else includes
    if declared_paths:
        admissible = snapshot.staged | snapshot.modified_unstaged | snapshot.unmerged | set(to_stage)
        _refuse_declared_paths_without_change(declared_paths, is_only=only is not None, admissible=admissible)

    if to_stage:
        _stage_files(to_stage, project_root)

    # Partial staging would sweep undeclared working-tree hunks, so restage first.
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
    if run_quality_gates and quality_paths:
        handle_format(quality_paths)
        handle_lint(quality_paths)

    # Use a message file for the mandated footer without shell argument splitting.
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
    # Use actual committed paths: pathspecs can be dirs or unexpanded globs.
    try:
        committed_files = [p for p in repo.git.show("--name-only", "--format=", "HEAD").splitlines() if p]
    except GitCommandError:
        committed_files = list(pathspec)
    _record_commit_checkpoint_markers(project_root, committed_files)
    del system_role


def _refuse_declared_paths_without_change(
    declared_paths: list[str],
    *,
    is_only: bool,
    admissible: frozenset[str] | set[str],
) -> None:
    """Exit 2 naming every declared path that contributes no change git will record.

    A declared path is admissible when it (or a path beneath it, treated as a
    directory prefix) is a member of ``admissible``.
    """
    offending = sorted(
        path
        for path in declared_paths
        if path not in admissible and not any(q.startswith(f"{path}/") for q in admissible)
    )
    if not offending:
        return
    channel = "--only" if is_only else "--include"
    print(f"ERROR: {channel} path(s) contribute no change git will record:", file=sys.stderr)
    for path in offending:
        print(f"  {path}", file=sys.stderr)
    print(
        "\nEach declared path must be staged, modified-and-unstaged, unmerged, newly\n"
        "added (untracked and picked up for staging), or a directory containing such a\n"
        "path. Verify it exists, is not gitignored, and carries a pending change.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _resolve_context_payload_paths(paths: list[str], project_root: Path, context_root: Path | None) -> list[str]:
    if not paths:
        return []
    resolved = validate_context_paths(paths, project_root, context_root)
    if len(resolved) != len(paths):
        print("ERROR: one or more paths were rejected outside the invocation context", file=sys.stderr)
        raise SystemExit(1)
    return resolved


def _display_context_paths(paths: list[str], project_root: Path, context_root: Path | None) -> list[str]:
    if context_root is None:
        return []
    return [(project_root / path).resolve().relative_to(context_root.resolve()).as_posix() for path in paths]


def _commit_active_merge(
    repo: Repo,
    message: str,
    *,
    project_root: Path,
    context_root: Path | None,
    run_quality_gates: bool,
    enforce_context_bound: bool,
    human_involved: bool = False,
) -> None:
    """Close an active merge as a full-index commit."""
    snapshot = working_tree_snapshot(project_root)
    if snapshot.unmerged:
        print("ERROR: unresolved paths remain during merge commit:", file=sys.stderr)
        for path in sorted(snapshot.unmerged):
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(1)

    if enforce_context_bound:
        scope_resolution = resolve_workspace_scope_resolution(project_root, context_root=context_root)
        eligible_paths = set(scope_resolution.repository_scoped_dirty_paths)
        index_paths = {path for path in repo.git.diff("--cached", "--name-only", "HEAD").splitlines() if path}
        disallowed_paths = sorted(index_paths - eligible_paths)
        if disallowed_paths:
            print("ERROR: merge index contains paths outside the invocation context:", file=sys.stderr)
            for path in disallowed_paths:
                print(f"  {path}", file=sys.stderr)
            raise SystemExit(1)

    quality_paths = _merge_quality_paths(repo, project_root)
    if run_quality_gates and quality_paths:
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
        obligations = main_only_action_ids_for_files(committed_files, project_root)
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


async def _commit_reviewers_async(project_root: Path, initiator_session_id: str) -> tuple[tuple[str, str], ...]:
    """Resolve every live commit-review session open for this project and driver."""
    runtime_db = await get_db()
    return await list_live_commit_reviewers_for_initiator(
        runtime_db, project_root, initiator_session_id, SlashCommand.NEXT_REVIEW_COMMITS.value
    )


def _resolve_open_commit_reviewers(project_root: Path) -> tuple[tuple[str, str], ...]:
    """Resolve the open commit reviewers for this driver as (session id, mode) pairs.

    Advisory only — this backs a printed hint, never a gate. Any resolution
    failure (no session identity, no runtime, an unreachable database) yields
    an empty result so the caller falls back to the start-only form; resolving
    this hint can never become a new way for ``telec code commit`` to fail.

    Every open reviewer is reported with its mode rather than one arbitrary
    holder: mode is part of the review subject, so a bare session id could
    address the doc-hygiene lane while the series needs the code lane.
    """
    initiator_session_id = get_session_id()
    if not initiator_session_id:
        return ()
    try:
        return asyncio.run(_commit_reviewers_async(project_root, initiator_session_id))
    except (OperationalError, OSError, RuntimeError):
        return ()


def _print_commit_review_guidance(project_root: Path) -> None:
    """Print the active commit-gate continuation instructions for shared main.

    The sealed contract makes ``--approved`` the single gate for any commit on
    main; the bare ``telec code commit`` invocation enters the commit gate. The
    caller owns the exit code, but the printed surface is a continuation
    instruction: commit or reach a concrete blocker before reporting done.
    """
    open_reviewers = _resolve_open_commit_reviewers(project_root)
    documentation_patterns = ", ".join(_NON_CODE_DOCUMENTATION_PATTERNS)
    standalone_prose_patterns = ", ".join(_STANDALONE_PROSE_PATTERNS)
    agent_artifact_patterns = ", ".join(CHECKPOINT_BASE_AGENTS_BINDING.scope.include)
    if open_reviewers:
        already_open = "".join(
            f"     already open at {mode or 'unknown'}: telec sessions send {session_id} "
            "'review commits <sha1,sha2,...>'\n"
            for session_id, mode in open_reviewers
        )
        review_dispatch = (
            "   Reuse the reviewer already open at the mode this series needs; a different lane\n"
            "   gets its own reviewer (--mode fast for doc-hygiene, --mode med for code review):\n"
            "     telec sessions run --command next-review-commits --args '<sha1,sha2,...>' --mode <fast|med>\n"
            + already_open
        )
    else:
        review_dispatch = (
            "   Start the reviewer for this series (--mode fast for doc-hygiene, --mode med for code review):\n"
            "     telec sessions run --command next-review-commits --args '<sha1,sha2,...>' --mode <fast|med>\n"
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
        f"   Documentation snippets ({DOC_LAYER_PATTERN}) or agent artifacts ({agent_artifact_patterns}) -> required:\n"
        "       dispatch an independent doc-hygiene review (you may not review your own).\n"
        f"   Standalone descriptive prose ({standalone_prose_patterns}) outside {DOC_LAYER_PATTERN} -> no\n"
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
    if scope_resolution.kind is not WorkspaceScopeKind.WORKTREE:
        return
    doc_layer_paths = forbidden_slug_worktree_doc_paths(project_root, pathspec)
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
    return list(scope_resolution.repository_scoped_dirty_paths)


def _changed_paths(scope_resolution: WorkspaceScopeResolution) -> list[str]:
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

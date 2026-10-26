"""CLI handlers for ``telec repo`` namespace."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import OperationalError

from teleclaude.cli.session_auth import ResolvedCliIdentity, resolve_cli_identity
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError, parse_command_args
from teleclaude.cli.telec.handlers._code_branch_publish import publish_committed_todo_branch
from teleclaude.cli.telec.handlers._code_commit_guidance import (
    _commit_stage_paths,
    _print_commit_review_guidance,
)
from teleclaude.cli.telec.handlers._code_commit_success import record_commit_success
from teleclaude.cli.telec.handlers._code_git_state import (
    PARTIAL_STAGING_RECOVERY_TEMPLATE,
    PATH_ARGUMENT_SEPARATOR,
    dirty_paths,
    get_unmerged_files,
    get_untracked_files,
    resolve_current_branch,
    working_tree_snapshot,
)
from teleclaude.cli.telec.handlers._code_invocation import resolve_invocation_state
from teleclaude.cli.telec.handlers._code_maintenance import handle_code_maintenance
from teleclaude.cli.telec.handlers._code_post_commit import handle_code_post_commit
from teleclaude.cli.telec.handlers._code_post_merge import handle_code_post_merge
from teleclaude.cli.telec.handlers._code_pre_commit import handle_code_pre_commit
from teleclaude.cli.telec.handlers._code_stamp import handle_code_stamp
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import REPO_COMMIT, REPO_OWNERS
from teleclaude.cli.telec.surface_types import HookEntryVerb, TelecCommand
from teleclaude.commit_identity import (
    PLANNED_TODO_TRAILER_KEY,
    TODO_TRAILER_KEY,
    CommitIdentityUnresolvable,
    CommitMessageMetadataReserved,
    compose_commit_footer,
    resolve_commit_identity_from_caller,
    validate_authored_commit_message,
)
from teleclaude.core.db import get_db
from teleclaude.core.dirty_path_owners import resolve_dirty_path_owners
from teleclaude.core.models import Session
from teleclaude.core.roles import RoleName
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.workflow_store.store import get_workflow_store_sync
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_lock import main_branch_lock, wait_for_index_lock_clear
from teleclaude.project_root import (
    forbidden_slug_worktree_agent_artifact_paths,
    forbidden_slug_worktree_doc_paths,
    resolve_invocation_roots,
    resolve_project_root,
)
from teleclaude.quality.gate import QualityGateLeg
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    resolve_workspace_scope_resolution,
    validate_context_paths,
    validate_scoped_paths,
)
from teleclaude.session_identity import get_session_id
from teleclaude.session_scoping import clear as clear_session_paths
from teleclaude.session_scoping import declare as declare_session_paths
from teleclaude.session_scoping import resolve_workspace
from teleclaude.slug import validate_slug

logger = get_logger(__name__)
_COMMIT_MESSAGE_RE = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+")
# The doc layer is authored at prepare on `main` and folded at integration; a slug
# worktree commit must never touch it. Deliberately narrower than
# `NON_CODE_DOCUMENTATION_PATTERNS` so the guard only refuses the doc layer
# itself, not incidental prose elsewhere in the tree.
_CODE_OWNERS_NO_POSITIONALS = "telec repo owners takes no positional arguments"
_CODE_OWNERS_QUERY_FAILURE = "telec repo owners failed: {error}"
_CODE_CAPABILITY_REQUIRED = "ERROR: telec repo {command} requires the code capability"
_COMMIT_CAPABILITY_REQUIRED = "ERROR: telec repo {command} requires the code or docs capability"
_MERGE_WORKTREE_DIFF_ARGUMENTS = ("--name-only", "-z", "--")
_NUL_CHARACTER = "\x00"
_ERR_TODO_LOOKUP = "ERROR: cannot resolve todo association for {slug!r}: {error}"
_TODO_ASSOCIATION_LINE = "{key}: {slug}"
_DOC_LAYER_WORKTREE_ERROR = "ERROR: doc-layer paths cannot be committed from a slug worktree:"
_DOC_LAYER_WORKTREE_GUIDANCE = (
    "\nThe doc layer is authored at prepare on main and folded at integration; "
    "the work phase executes a frozen contract. If a doc need surfaced mid-build, "
    "kick back instead of editing docs/** here:\n"
    '  telec todo stamp <slug> --kickback --reason "<why the plan cannot be built>"'
)
_AGENT_ARTIFACT_WORKTREE_ERROR = "ERROR: agent-artifact source paths cannot be committed from a slug worktree:"
_AGENT_ARTIFACT_WORKTREE_GUIDANCE = (
    "\nAgent-artifact sources are authored on main in the session where their intent was decided; "
    "remove these paths from the worktree commit and route the artifact change to that session."
)
_WORKTREE_REFUSAL_PATH_TEMPLATE = "  {path}"
_ADD_UNKNOWN_FLAG_TEMPLATE = "ERROR: unknown flag: {token}\nUsage: telec repo add <path> [<path> ...]"
_ADD_USAGE = (
    "Usage: telec repo add <path> [<path> ...]\n"
    "\n"
    "Declares paths for the next `telec repo commit`; NEW files are also staged.\n"
    "Modified tracked files are declared without staging because pathspec commits\n"
    "them directly from the working tree. Clean and not-yet-created paths are\n"
    "declared the same way — declare as you start on a file, or the moment you\n"
    "notice one isn't declared."
)
_COMMIT_MESSAGE_COUNT_ERROR = (
    "ERROR: telec repo commit accepts exactly one quoted message.\n"
    "If a path was consumed as part of the message, place path flags after "
    "the message (or after --approved):\n"
    '  telec repo commit --approved "<message>" --only <path> ...'
)
_COMMIT_ONLY_WITH_INCLUDE_ERROR = (
    "ERROR: --only cannot be combined with --include.\n"
    '  telec repo commit --approved "<message>" --only <path> [<path> ...]'
)
_COMMIT_GATE_HELP = (
    "telec repo commit is the sealed canonical commit interface.\n"
    "Use --approved to acknowledge the agent-owned commit gate:\n"
    '  telec repo commit --approved "type(scope): subject"'
)
_COMMIT_MESSAGE_REQUIRED_ERROR = (
    'ERROR: --approved requires a quoted commit message.\n  telec repo commit --approved "type(scope): subject"'
)
_UNTRACKED_DECLARE_GUIDANCE_TEMPLATE = (
    "\nIf intentional, declare them:\n"
    "  telec repo add {paths}  # then re-run commit\n"
    "  telec repo commit --approved '<msg>' --include {paths}\n"
    "If temp/scratch, leave them — they stay untracked.\n"
)
_NOTHING_DECLARED_DIRTY_TREE_ERROR = (
    "ERROR: nothing declared, and the workspace holds dirty paths. This commit "
    "would silently record nothing. Declare what you are working on with "
    "`telec repo add <path>...`, or pass `--include <path>` here."
)
_NOTHING_IN_SCOPE_ERROR = (
    "Nothing in workspace scope to commit. For NEW files, declare them with "
    "`telec repo add <path>` first, or pass `--include <path>` here."
)
_ADD_SESSION_CHECKOUT_UNRESOLVED = (
    "ERROR: telec repo add could not resolve the checkout of session {session_id}; nothing was staged or declared."
)
_ADD_NOT_DECLARED_FOREIGN_CHECKOUT = (
    "Not declared: the invocation repository {invocation} is not the session checkout {checkout}.\n"
    "Staged as usual; the session's declarations carry only paths in its own checkout:"
)


class CodeSubcommand(StrEnum):
    """Closed command vocabulary for capability routing."""

    LINT = "lint"
    TEST = "test"
    FORMAT = "format"
    COMMIT = "commit"
    ADD = "add"
    OWNERS = "owners"
    STAMP = "stamp"
    BLUEPRINT = "blueprint"
    MAINTENANCE = "maintenance"


_CODE_CAPABILITY_SUBCOMMANDS = frozenset(
    {
        CodeSubcommand.TEST,
        CodeSubcommand.FORMAT,
        CodeSubcommand.BLUEPRINT,
    }
)
_COMMIT_SUBCOMMANDS = frozenset(
    {CodeSubcommand.COMMIT, CodeSubcommand.ADD, CodeSubcommand.OWNERS, CodeSubcommand.STAMP}
)


_HOOK_ENTRY_HANDLERS: dict[HookEntryVerb, Callable[[list[str]], None]] = {
    HookEntryVerb.PRE_COMMIT: handle_code_pre_commit,
    HookEntryVerb.POST_COMMIT: handle_code_post_commit,
    HookEntryVerb.POST_MERGE: handle_code_post_merge,
}


def _hook_entry_verb(args: list[str]) -> HookEntryVerb | None:
    """Return the hook-entry verb named by the first argument, or None when it names none."""
    try:
        return HookEntryVerb(args[0]) if args else None
    except ValueError:
        return None


def handle_code(args: list[str]) -> None:
    """Route ``telec repo <subcommand>`` to the correct handler."""
    if not args:
        print(_usage(TelecCommand.REPO))
        return
    verb = _hook_entry_verb(args)
    if verb is not None:
        _HOOK_ENTRY_HANDLERS[verb](args[1:])
        return
    try:
        sub = CodeSubcommand(args[0])
    except ValueError:
        print(_usage(TelecCommand.REPO))
        return
    rest = args[1:]
    _require_code_capability(sub)
    if sub is CodeSubcommand.LINT:
        from teleclaude.cli.telec.handlers.quality import (  # noqa: PLC0415 - each quality command owns its handler import.
            handle_lint,
        )

        handle_lint(rest)
    elif sub is CodeSubcommand.TEST:
        from teleclaude.cli.telec.handlers.quality import (  # noqa: PLC0415 - each quality command owns its handler import.
            handle_test,
        )

        handle_test(rest)
    elif sub is CodeSubcommand.FORMAT:
        from teleclaude.cli.telec.handlers.quality import (  # noqa: PLC0415 - each quality command owns its handler import.
            handle_format,
        )

        handle_format(rest)
    elif sub is CodeSubcommand.COMMIT:
        handle_code_commit(rest)
    elif sub is CodeSubcommand.ADD:
        handle_code_add(rest)
    elif sub is CodeSubcommand.OWNERS:
        handle_code_owners(rest)
    elif sub is CodeSubcommand.STAMP:
        handle_code_stamp(rest)
    elif sub is CodeSubcommand.BLUEPRINT:
        from teleclaude.cli.telec.handlers.blueprint import handle_code_blueprint  # noqa: PLC0415

        handle_code_blueprint(rest)
    elif sub is CodeSubcommand.MAINTENANCE:
        handle_code_maintenance(rest)


def _require_code_capability(command: CodeSubcommand) -> None:
    """Refuse commands whose owning project capability is unsubscribed."""
    state = resolve_invocation_state()
    if command is CodeSubcommand.LINT:
        return
    if command in _CODE_CAPABILITY_SUBCOMMANDS and not state.capabilities.code:
        print(_CODE_CAPABILITY_REQUIRED.format(command=command.value), file=sys.stderr)
        raise SystemExit(1)
    if command in _COMMIT_SUBCOMMANDS and not (
        state.is_non_project_invocation_context or state.capabilities.commit_enabled
    ):
        print(_COMMIT_CAPABILITY_REQUIRED.format(command=command.value), file=sys.stderr)
        raise SystemExit(1)


def handle_code_owners(args: list[str]) -> None:
    """Print declaration owners for every dirty path of the canonical checkout."""
    parsed = parse_command_args(REPO_OWNERS, args)
    if parsed.positionals:
        raise CliUsageError(_CODE_OWNERS_NO_POSITIONALS)

    project_root = resolve_project_root(resolve_invocation_roots().repository_root)
    try:
        result = asyncio.run(resolve_dirty_path_owners(project_root))
    except Exception as exc:
        print(_CODE_OWNERS_QUERY_FAILURE.format(error=exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.as_json(), indent=2, sort_keys=True))


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
       delta) — the partial-staging guard in ``telec repo commit`` blocks
       these because ``git commit -- <path>`` would otherwise sweep
       unstaged hunks. This command is that guard's prescribed recovery:
       running ``git add`` fully restages the file so the staged version
       matches the working tree, removing the ambiguity.

    A successful call invoked from inside the session's checkout declares its
    paths to session-scoping; invoked from a different repository it stages as
    usual and declares nothing. Modified-tracked files that are NOT
    partial-staged therefore succeed without index mutation.
    A clean tracked path and a path that does not exist yet are declared the
    same way: declaring is bookkeeping for work about to start, not a claim
    about current git state, so declaring before the first touch or ahead of a
    file's creation both succeed and stage nothing.
    """
    positionals: list[str] = []
    for token in args:
        if token.startswith("-"):
            print(
                _ADD_UNKNOWN_FLAG_TEMPLATE.format(token=token),
                file=sys.stderr,
            )
            raise SystemExit(2)
        positionals.append(token)

    if not positionals:
        print(_ADD_USAGE, file=sys.stderr)
        raise SystemExit(2)

    state = resolve_invocation_state()
    project_root = state.repository_root
    validated_positionals = validate_context_paths(positionals, project_root, state.context_root)
    if len(validated_positionals) != len(positionals):
        print("ERROR: one or more paths were rejected outside the invocation context", file=sys.stderr)
        raise SystemExit(1)
    positionals = validated_positionals
    session_id = get_session_id()
    session_checkout = _resolve_session_checkout_root(session_id) if session_id else None
    if session_id and session_checkout is None:
        print(_ADD_SESSION_CHECKOUT_UNRESOLVED.format(session_id=session_id), file=sys.stderr)
        raise SystemExit(1)
    foreign_checkout = session_checkout is not None and session_checkout != project_root.resolve()
    untracked = set(get_untracked_files(project_root))
    unmerged = set(get_unmerged_files(project_root))
    dirty = dirty_paths(project_root)
    # Partial-staging: file has BOTH staged changes AND a later working-tree
    # delta. `telec repo add` is the recovery path the partial-staging guard
    # points at, so it must accept these files and fully (re)stage them.
    repo = Repo(str(project_root))
    staged_now = set(repo.git.diff("--cached", "--name-only").strip().splitlines())
    unstaged_now = set(repo.git.diff("--name-only").strip().splitlines())
    partial_staged = staged_now & unstaged_now

    stageable: list[str] = []
    already_tracked: list[str] = []
    not_yet_dirty: list[str] = []

    for path in positionals:
        # Untracked/unmerged/partial-staged paths all exist on disk by
        # construction, so checking them first never misclassifies a path
        # that does not exist yet. A clean tracked path and a path that does
        # not exist yet fall to the same bucket: nothing for git to stage,
        # so the declaration is bookkeeping only.
        if path in untracked or path in unmerged or path in partial_staged:
            stageable.append(path)
        elif path in dirty:
            already_tracked.append(path)
        else:
            not_yet_dirty.append(path)

    if already_tracked and not foreign_checkout:
        # Modified tracked paths are declarations; pathspec commit needs no index mutation.
        print(
            "Declared already tracked + modified path(s); no staging needed (the pathspec\n"
            "commit takes them straight from the working tree):\n  " + "\n  ".join(already_tracked),
            file=sys.stderr,
        )

    if not_yet_dirty and not foreign_checkout:
        print(
            "Declared path(s) with nothing yet for git to stage (clean or not created yet):\n  "
            + "\n  ".join(not_yet_dirty),
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

    if session_id and not foreign_checkout:
        declare_session_paths(session_id, positionals)
    elif foreign_checkout:
        print(
            _ADD_NOT_DECLARED_FOREIGN_CHECKOUT.format(invocation=project_root, checkout=session_checkout)
            + "\n  "
            + "\n  ".join(positionals),
            file=sys.stderr,
        )


def _resolve_session_checkout_root(session_id: str) -> Path | None:
    """Resolve the checkout root the session's record belongs to, or None when it cannot be established."""
    try:
        session = asyncio.run(_load_session_async(session_id))
    except (OperationalError, OSError, RuntimeError):
        return None
    if session is None or not session.project_path:
        return None
    try:
        working_dir = resolve_working_dir(session.project_path, session.subdir)
    except ValueError:
        return None
    root = resolve_workspace(working_dir).root
    return Path(root).resolve() if root else None


async def _load_session_async(session_id: str) -> Session | None:
    """Fetch the session row through the runtime database."""
    return await (await get_db()).get_session(session_id)


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

    After a successful commit, a todo slug worktree publishes its branch to
    origin outside the project-wide commit lock. Publication failures are
    reported without changing the recorded commit's success.

    Safety primitives:
    1. Orchestrator restriction.
    2. main-branch lock serialises all ``_commit_under_lock`` bodies.
    3. ``telec repo commit`` formats native-code paths before invoking Git.
    4. Git's pre-commit hook runs the selected staged-content quality gate for
       every route into a commit.
    5. ``--approved`` is the commit gate; bare invocation prints the
       review-routing guidance (exit 0) and never commits.
    6. The pathspec itself bounds the commit — no separate scope-enforcement
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
    parsed = parse_command_args(REPO_COMMIT, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(_COMMIT_MESSAGE_COUNT_ERROR, file=sys.stderr)
        raise SystemExit(2)

    approved = parsed.has(F.FLAG_COMMIT_APPROVED)
    human_involved_reason = parsed.value(F.FLAG_HUMAN_INVOLVED_COMMIT)
    includes = list(parsed.values(F.FLAG_COMMIT_INCLUDE))
    only = list(parsed.values(F.FLAG_COMMIT_ONLY))
    todo_slug = parsed.value(F.FLAG_COMMIT_TODO)

    if includes and only:
        print(_COMMIT_ONLY_WITH_INCLUDE_ERROR, file=sys.stderr)
        raise SystemExit(2)

    message = positionals[0] if positionals else None
    caller_identity = resolve_cli_identity()
    state = resolve_invocation_state()
    project_root = state.repository_root
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
        if current_branch == "main" and caller_identity.role != RoleName.INTEGRATOR.value:
            _print_commit_review_guidance(project_root, state.context_root)
            raise SystemExit(1 if forgot_gate else 0)
        print(_COMMIT_GATE_HELP, file=sys.stderr)
        raise SystemExit(2 if forgot_gate else 0)

    # --approved → commit. Message required.
    if message is None:
        print(_COMMIT_MESSAGE_REQUIRED_ERROR, file=sys.stderr)
        raise SystemExit(2)

    try:
        validate_authored_commit_message(message)
    except CommitMessageMetadataReserved as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None

    human_involved = _resolve_human_involvement_declaration(human_involved_reason)

    with main_branch_lock():
        _commit_under_lock(
            message=message,
            includes=includes,
            project_root=project_root,
            context_root=state.context_root,
            quality_gate_legs=state.quality_gate_legs,
            enforce_context_bound=state.is_non_project_invocation_context,
            caller_identity=caller_identity,
            only=only or None,
            human_involved=human_involved,
            todo_slug=todo_slug,
        )

    publish_committed_todo_branch(project_root)


def _resolve_human_involvement_declaration(reason: str | None) -> bool:
    """Resolve one commit-local declaration in-process; never fail the commit over it."""
    if reason is None:
        return False
    session_id = get_session_id()
    if not session_id:
        return False
    try:
        return asyncio.run(_resolve_human_involvement_async(session_id, reason))
    except (OperationalError, OSError, RuntimeError):
        # The record must never make committing depend on the daemon's session
        # store being reachable; an unreadable store resolves to no involvement.
        return False


async def _resolve_human_involvement_async(session_id: str, reason: str) -> bool:
    """Await the runtime database and resolve through the core involvement seam."""
    from teleclaude.core.human_involvement import (  # noqa: PLC0415
        HumanInvolvementReasonInvalid,
        HumanInvolvementSurface,
        resolve_human_involvement,
    )

    runtime_db = await get_db()
    try:
        resolution = await resolve_human_involvement(
            session_id=session_id,
            reason=reason,
            session_store=runtime_db,
            surface=HumanInvolvementSurface.COMMIT,
        )
    except HumanInvolvementReasonInvalid as exc:
        print(f"Error: {exc}; rerun without --human-involved if the act is not human-involved.", file=sys.stderr)
        raise SystemExit(2) from None
    return resolution.involved


def _commit_under_lock(
    *,
    message: str,
    includes: list[str],
    project_root: Path,
    context_root: Path | None,
    quality_gate_legs: frozenset[QualityGateLeg],
    enforce_context_bound: bool,
    caller_identity: ResolvedCliIdentity,
    only: list[str] | None = None,
    human_involved: bool = False,
    todo_slug: str | None = None,
) -> None:
    """Commit the resolved pathspec while holding the main-branch lock."""
    # Clear stale index locks before work, minimizing the flock window.
    wait_for_index_lock_clear(project_root)
    _check_commit_message(message, project_root)
    todo_association = _resolve_commit_todo_association(project_root, todo_slug)
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
            quality_gate_legs=quality_gate_legs,
            enforce_context_bound=enforce_context_bound,
            caller_identity=caller_identity,
            human_involved=human_involved,
            todo_association=todo_association,
        )
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

    # Governed source contracts are frozen in slug worktrees.
    _refuse_frozen_paths_in_slug_worktree(scope_resolution, project_root, pathspec)

    # Explain skipped new files before an empty-scope failure hides recovery.
    if only is None and untracked_unstaged_in_scope:
        print(
            f"Note: {len(untracked_unstaged_in_scope)} new file(s) in scope were not included in this commit:",
            file=sys.stderr,
        )
        for path in untracked_unstaged_in_scope:
            print(f"  {path}", file=sys.stderr)
        print(
            _UNTRACKED_DECLARE_GUIDANCE_TEMPLATE.format(
                paths=PATH_ARGUMENT_SEPARATOR.join(untracked_unstaged_in_scope)
            ),
            file=sys.stderr,
        )

    if not pathspec:
        if scope_resolution.declared_nothing_over_dirty_tree:
            print(_NOTHING_DECLARED_DIRTY_TREE_ERROR, file=sys.stderr)
            raise SystemExit(1)
        print(_NOTHING_IN_SCOPE_ERROR, file=sys.stderr)
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
            PARTIAL_STAGING_RECOVERY_TEMPLATE.format(paths=PATH_ARGUMENT_SEPARATOR.join(sorted(overlap))),
            file=sys.stderr,
        )
        raise SystemExit(1)

    quality_paths = [path for path in pathspec if (project_root / path).exists()]
    if quality_gate_legs and quality_paths:
        _format_commit_paths(quality_paths, quality_gate_legs)

    # Use a message file for the mandated footer without shell argument splitting.
    stdout, stderr = _commit_repo_with_message(
        repo,
        message,
        commit_args=("-F", "{message_file}", "--", *pathspec),
        caller_identity=caller_identity,
        human_involved=human_involved,
        todo_association=todo_association,
    )
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    committed_files = record_commit_success(repo, project_root, pathspec)
    _clear_landed_commit_declarations(committed_files, only=only)


def _clear_landed_commit_declarations(committed_files: list[str], *, only: list[str] | None) -> None:
    """Clear exactly the declarations this landed commit carried."""
    session_id = get_session_id()
    if not session_id:
        return
    cleared = clear_session_paths(session_id, committed_files)
    logger.info(
        "session_scoping.declaration_boundary_landed",
        session_id=session_id,
        scope="only" if only is not None else "full",
        cleared_paths=list(cleared),
    )


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


def _resolve_commit_todo_association(project_root: Path, slug: str | None) -> tuple[str, str] | None:
    """Resolve the historical footer name from the owning workflow store."""
    if slug is None:
        return None
    try:
        validate_slug(slug)
        recorded = get_workflow_store_sync(project_root).slug_recorded_sync(slug)
    except (OSError, OperationalError, RuntimeError, ValueError) as exc:
        print(_ERR_TODO_LOOKUP.format(slug=slug, error=exc), file=sys.stderr)
        raise SystemExit(1) from exc
    key = TODO_TRAILER_KEY if recorded else PLANNED_TODO_TRAILER_KEY
    return key, slug


def _commit_active_merge(
    repo: Repo,
    message: str,
    *,
    project_root: Path,
    context_root: Path | None,
    quality_gate_legs: frozenset[QualityGateLeg],
    enforce_context_bound: bool,
    caller_identity: ResolvedCliIdentity,
    human_involved: bool = False,
    todo_association: tuple[str, str] | None = None,
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
    formatted_paths = False
    if quality_gate_legs and quality_paths:
        formatted_paths = _format_commit_paths(quality_paths, quality_gate_legs)
    if formatted_paths:
        changed_paths = _merge_paths_changed_in_working_tree(repo, quality_paths)
        if changed_paths:
            _stage_files(changed_paths, project_root)

    stdout, stderr = _commit_repo_with_message(
        repo,
        message,
        commit_args=("-F", "{message_file}"),
        caller_identity=caller_identity,
        human_involved=human_involved,
        todo_association=todo_association,
    )
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    record_commit_success(repo, project_root, quality_paths)


def _format_commit_paths(
    quality_paths: list[str],
    quality_gate_legs: frozenset[QualityGateLeg],
) -> bool:
    """Format native-code paths before Git runs the staged-content hook gate."""
    from teleclaude.cli.telec.handlers.quality import (  # noqa: PLC0415 - commit quality checks need formatting only here.
        handle_format,
    )

    if QualityGateLeg.NATIVE not in quality_gate_legs:
        return False
    handle_format(quality_paths)
    return True


def _merge_paths_changed_in_working_tree(repo: Repo, quality_paths: list[str]) -> list[str]:
    """Return formatted merge paths whose working-tree content differs from the index."""
    output = repo.git.diff(*_MERGE_WORKTREE_DIFF_ARGUMENTS, *quality_paths)
    return [path for path in output.split(_NUL_CHARACTER) if path]


def _commit_repo_with_message(
    repo: Repo,
    message: str,
    *,
    commit_args: tuple[str, ...],
    caller_identity: ResolvedCliIdentity,
    human_involved: bool = False,
    todo_association: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Commit with the resolved author identity and mandated footer.

    Resolves the authoring identity fresh for every commit — an agent session
    stamps its own bot identity as ``--author``; a genuine terminal-login human
    stamps nothing (git's own ambient identity is already theirs); anything
    else is a resolution failure and stops the commit rather than silently
    misattributing it.
    """
    try:
        git_identity, session_id = resolve_commit_identity_from_caller(caller_identity)
    except CommitIdentityUnresolvable as exc:
        raise SystemExit(str(exc)) from exc

    final_message = compose_commit_footer(
        message,
        session_id=session_id,
        human_involved=human_involved,
        todo_association=todo_association,
    )

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


def _refuse_frozen_paths_in_slug_worktree(
    scope_resolution: WorkspaceScopeResolution,
    project_root: Path,
    pathspec: list[str],
) -> None:
    """Refuse commits to source contracts frozen outside slug worktrees.

    Exits before any staging/format/lint/commit runs. The integration worktree
    is excluded because it legitimately commits frozen paths during delivery.
    """
    if scope_resolution.kind is not WorkspaceScopeKind.WORKTREE:
        return
    doc_layer_paths = forbidden_slug_worktree_doc_paths(project_root, pathspec)
    agent_artifact_paths = forbidden_slug_worktree_agent_artifact_paths(project_root, pathspec)
    if not doc_layer_paths and not agent_artifact_paths:
        return
    if doc_layer_paths:
        print(_DOC_LAYER_WORKTREE_ERROR, file=sys.stderr)
        for path in doc_layer_paths:
            print(_WORKTREE_REFUSAL_PATH_TEMPLATE.format(path=path), file=sys.stderr)
        print(_DOC_LAYER_WORKTREE_GUIDANCE, file=sys.stderr)
    if agent_artifact_paths:
        print(_AGENT_ARTIFACT_WORKTREE_ERROR, file=sys.stderr)
        for path in agent_artifact_paths:
            print(_WORKTREE_REFUSAL_PATH_TEMPLATE.format(path=path), file=sys.stderr)
        print(_AGENT_ARTIFACT_WORKTREE_GUIDANCE, file=sys.stderr)
    raise SystemExit(1)


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

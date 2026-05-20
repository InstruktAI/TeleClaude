"""CLI handlers for ``telec code`` namespace."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from teleclaude.cli.telec.handlers.quality import handle_format, handle_lint, handle_test
from teleclaude.cli.telec.help import _usage
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_lock import main_branch_lock
from teleclaude.project_root import resolve_invocation_cwd, resolve_workspace_root
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    resolve_workspace_scope_resolution,
)
from teleclaude.session_identity import get_system_role

# Mandated commit trailer (repo Commits policy). Auto-appended so it can never
# be forgotten; idempotent — skipped if the message already carries it.
_COMMIT_TRAILER = (
    "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
    "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
)
_TRAILER_MARKER = "🤖 Generated with [TeleClaude]"


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
    elif sub == "commit":
        handle_code_commit(rest)
    elif sub == "changed":
        handle_code_changed(rest)
    else:
        print(_usage("code"))


def handle_code_changed(args: list[str]) -> None:
    """List workspace-scoped changed files."""
    _ = args
    project_root = resolve_workspace_root(resolve_invocation_cwd())
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
    3. Pre-commit hook owns format + lint inside git's own atomicity.
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
    for token in args:
        if token == "--approved":
            approved = True
            mode_include = False
        elif token == "--include":
            mode_include = True
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
        else:
            positionals.append(token)

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
    project_root = resolve_workspace_root(resolve_invocation_cwd())

    # The absence of --approved is the trigger: surface guidance, never commit.
    # On main + non-integrator → Path A/B/C. Off main / integrator → short help.
    # An already-drafted message is fine to pass; it's just ignored until the
    # --approved re-run.
    if not approved:
        current_branch = _current_branch(project_root)
        if current_branch == "main" and system_role != "integrator":
            _print_abc_classification()
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
    for its owner. The pre-commit hook owns format + lint inside git's own
    atomicity.
    """
    scope_resolution = resolve_workspace_scope_resolution(project_root)
    scope_paths = _commit_stage_paths(scope_resolution)

    # Merge scope plus includes, preserving order, deduped. The result is both
    # the staging target and the commit pathspec.
    seen: set[str] = set()
    pathspec: list[str] = []
    for path in scope_paths:
        if path not in seen:
            seen.add(path)
            pathspec.append(path)
    for path in includes:
        if path not in seen:
            seen.add(path)
            pathspec.append(path)

    if not pathspec:
        print(
            "Nothing in workspace scope to commit. Run `telec code changed` to "
            "see what telec would stage, and use `--include <path>` to add files "
            "outside that list.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Stage anything in our pathspec that isn't already staged. `git add` is
    # a no-op for clean files, so declared includes that have no change won't
    # show up in the index — we catch that case below.
    pre_staged_set = set(_get_staged_files(project_root, include_deletions=True))
    to_stage = [path for path in pathspec if path not in pre_staged_set]
    if to_stage:
        _stage_files(to_stage, project_root)

    # Every --include path must contribute a change. If a declared include is
    # still not in the staged set after `git add`, the agent named a path with
    # no change — fail early with a precise error rather than committing scope
    # silently.
    if includes:
        staged_after = set(_get_staged_files(project_root, include_deletions=True))
        missing = [path for path in includes if path not in staged_after]
        if missing:
            print(
                "ERROR: --include path(s) have no changes to commit:\n  " + "\n  ".join(missing),
                file=sys.stderr,
            )
            raise SystemExit(2)

    # Partial staging within our pathspec corrupts pre-commit's stash/restore
    # cycle. Foreign partial-staging is not our concern — it's outside the
    # pathspec and outside the hook's working set.
    _check_partial_staging(project_root, pathspec=pathspec)

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
        _, stdout, stderr = repo.git.commit("-F", msg_path, "--", *pathspec, with_extended_output=True)
    except GitCommandError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        os.unlink(msg_path)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    # system_role is retained on the signature for symmetry with prior gates;
    # the pathspec boundary makes a separate scope-enforcement step redundant.
    del system_role


def _print_abc_classification() -> None:
    """Print the Path A/B/C classification guidance for a shared-main commit.

    The sealed contract makes ``--approved`` the single gate for any commit on
    main; the bare ``telec code commit`` invocation surfaces this guidance and
    exits — the agent picks A, B, or C and re-runs with ``--approved`` and a
    message.
    """
    print(
        "Commits on main require classification.\n"
        "\n"
        "First, see what telec will stage and commit:\n"
        "  telec code changed\n"
        "\n"
        "If files outside that list also need to be in this commit (e.g., a file\n"
        "the human collaboratively edited that the scope heuristic missed),\n"
        "declare them explicitly with --include:\n"
        "  telec code commit --approved '<message>' --include <path> [<path> ...]\n"
        "\n"
        "Foreign files left in the index (staged by another session) are NOT\n"
        "committed by telec — the pathspec excludes them. Do not unstage them.\n"
        "\n"
        "  A) NON-FUNCTIONAL FILES ONLY (Markdown, YAML, doc snippets, state):\n"
        "     Include [skip ci] in the subject:\n"
        "       telec code commit --approved 'chore(scope): <subject> [skip ci]'\n"
        "\n"
        "  B) SMALL, SELF-EVIDENT FUNCTIONAL CHANGE (human is present):\n"
        "     State recommendation to the human, wait for approval, then:\n"
        "       telec code commit --approved '<type>(<scope>): <subject>'\n"
        "\n"
        "  C) FUNCTIONAL CHANGE + REVIEW:\n"
        "     Commit with human approval:\n"
        "       telec code commit --approved '<type>(<scope>): <subject>'\n"
        "     If this patch series has no /next-review-commits reviewer yet, dispatch one:\n"
        "       telec sessions run --command /next-review-commits --args '<sha1,sha2,...>'"
        " --agent <agent>\n"
        "     For every follow-up on the same patch series, send the new commit(s) to that reviewer:\n"
        "       telec sessions send <reviewer-session-id> 'review commits <sha1,sha2,...>'\n"
        "     To find the reviewer session id:\n"
        "       telec sessions list\n"
        "     BLOCKING: Do not proceed, end sessions, or report completion until the reviewer completes.\n"
        "     The completed turn must contain `REVIEW COMPLETE: commits ...` with a verdict.\n"
        "     Do not poll. Wait for the reviewer finished-turn notification.\n"
        "     Use the heartbeat only as the stale-notification fallback.\n"
        "     Then tail once and inspect the terminal report.\n"
        "     Commit reviews have no todo slug — do not instruct the reviewer to stamp.\n"
        "     If changes are requested, fix and send the new commit(s) to the same reviewer.\n"
        "     If no terminal report appears, clarify with the same reviewer.\n"
        "     Only `Verdict: APPROVE` closes the review gate.\n"
        "\n"
        "Explain which classification applies and why.",
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
    """Stage files via git add."""
    repo = Repo(str(project_root))
    repo.git.add("--", *files)


def _get_staged_files(project_root: Path, *, include_deletions: bool = False) -> list[str]:
    """Return list of staged file paths."""
    repo = Repo(str(project_root))
    diff_filter = "ACMRD" if include_deletions else "ACMR"
    output: str = repo.git.diff("--cached", "--name-only", f"--diff-filter={diff_filter}")
    return [f.strip() for f in output.strip().splitlines() if f.strip()]


def _check_partial_staging(project_root: Path, *, pathspec: list[str] | None = None) -> None:
    """Block commits with partially staged files inside our pathspec.

    Partial staging within the commit's pathspec corrupts the pre-commit
    stash/restore cycle. Foreign partial-staging (outside our pathspec) is
    not our concern — the commit doesn't touch it and the hook's working set
    doesn't include it.
    """
    repo = Repo(str(project_root))
    staged = set(repo.git.diff("--cached", "--name-only").strip().splitlines())
    unstaged = set(repo.git.diff("--name-only").strip().splitlines())
    overlap = staged & unstaged
    if pathspec is not None:
        overlap = overlap & set(pathspec)
    if overlap:
        print("ERROR: partially staged files detected.", file=sys.stderr)
        print("Pre-commit stash/restore would corrupt these files.\n", file=sys.stderr)
        for f in sorted(overlap):
            print(f"  {f}", file=sys.stderr)
        print(
            "\nFully stage each file, then re-run telec code commit:\n  git add -- " + " ".join(sorted(overlap)),
            file=sys.stderr,
        )
        raise SystemExit(1)


def _current_branch(project_root: Path) -> str:
    """Return the current git branch name."""
    repo = Repo(str(project_root))
    branch: str = repo.git.rev_parse("--abbrev-ref", "HEAD")
    return branch.strip()

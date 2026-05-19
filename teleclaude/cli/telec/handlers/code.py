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

# Extensions and filenames that indicate functional (runtime-affecting) code.
# Mirrors the wrapper's classification for consistency.
_FUNCTIONAL_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".hxx",
        ".rs",
        ".go",
        ".rb",
        ".java",
        ".kt",
        ".swift",
        ".m",
        ".mm",
        ".sql",
        ".toml",
        ".lock",
        ".mk",
    }
)
_FUNCTIONAL_NAMES = frozenset({"Makefile", "Dockerfile"})


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
    ``--approved``. No ``-m``, no ``-F``, no ``--``, no pathspecs, no git
    flags: nothing is forwarded to git. Staging and the pathspec commit are
    internal implementation details.

    Caller paths:
    - Outside tmux: the wrapper passes through to plain git; this command is
      not in the picture.
    - Inside tmux, autonomous agent: this command. Workspace scope drives
      staging. The final ``git commit`` runs with an explicit pathspec so
      anything else in the index (concurrent stage from another session,
      crash residue) is left untouched.
    - Inside tmux, supervised one-off:
      ``TELECLAUDE_COMMIT_APPROVED=1 git commit -- <paths>`` bypasses the
      wrapper redirect. This command is not in the picture.

    Safety primitives:
    1. Orchestrator restriction.
    2. main-branch lock serialises all ``_commit_under_lock`` bodies.
    3. Pre-commit hook owns format + lint inside git's own atomicity.
    4. Shared-main gate, two ordered stages for non-integrator commits:
       a. Path A/B/C classification — answered by ``--approved`` / ``[skip
          ci]``; decides whether this is the right commit strategy.
       b. Session-scope assertion — independent of ``--approved``; hard-fails
          when the index holds files outside this session's scope, unless the
          explicit ``TELECLAUDE_COMMIT_APPROVED`` override is set.
    """
    approved = "--approved" in args
    positionals = [a for a in args if a != "--approved"]
    if len(positionals) != 1 or positionals[0].startswith("-"):
        print(
            "ERROR: telec code commit takes exactly one quoted commit message and "
            "optionally --approved. No other arguments are accepted (no -m, -F, --, "
            "pathspecs, or git flags — nothing is forwarded to git; staging is "
            "automatic and scoped).\n"
            '  telec code commit "type(scope): subject"\n'
            '  telec code commit --approved "type(scope): subject"',
            file=sys.stderr,
        )
        raise SystemExit(2)
    message = positionals[0]

    system_role = get_system_role()
    project_root = resolve_workspace_root(resolve_invocation_cwd())

    with main_branch_lock():
        _commit_under_lock(
            message=message,
            project_root=project_root,
            system_role=system_role,
            approved=approved,
        )


def _commit_under_lock(
    *,
    message: str,
    project_root: Path,
    system_role: str | None,
    approved: bool = False,
) -> None:
    """Execute the commit sequence while holding the main-branch lock.

    Stages the files in the workspace scope and commits with an explicit
    pathspec. Anything else in the index (concurrent stage from another
    session, crash residue) is left untouched. The pre-commit hook owns
    format and lint inside git's own atomicity.
    """
    scope_resolution = resolve_workspace_scope_resolution(project_root)
    stage_paths = _commit_stage_paths(scope_resolution)

    if stage_paths:
        pre_staged_set = set(_get_staged_files(project_root, include_deletions=True))
        unstaged_stage_paths = [path for path in stage_paths if path not in pre_staged_set]
        if unstaged_stage_paths:
            _stage_files(unstaged_stage_paths, project_root)

    staged_for_commit = _get_staged_files(project_root, include_deletions=True)
    if not staged_for_commit:
        print("Nothing staged for commit.", file=sys.stderr)
        raise SystemExit(1)

    if not scope_resolution.scoped_dirty_paths and staged_for_commit:
        print(
            f"telec code commit: session scope unavailable; committing "
            f"{len(staged_for_commit)} pre-staged file(s): {', '.join(staged_for_commit)}",
            file=sys.stderr,
        )

    _check_partial_staging(project_root)

    # Two independent gates on shared main, ordered. Stage 1 (Path A/B/C)
    # decides "is this the right commit strategy" and is answered by
    # --approved or [skip ci]. Stage 2 (session scope) decides "is this
    # commit contaminated with another session's staged work" and is
    # answered only by the explicit TELECLAUDE_COMMIT_APPROVED override.
    # --approved never buys past stage 2; the integrator is exempt from both.
    current_branch = _current_branch(project_root)
    if current_branch == "main" and system_role != "integrator":
        if not approved:
            _classify_main_commit(message, staged_for_commit)
        _enforce_session_scope(staged_for_commit, scope_resolution)

    # Auto-append the mandated trailer (idempotent) and commit via a message
    # file — robust against multi-line content, no shell arg-splitting.
    final_message = _with_trailer(message)

    # Pathspec scopes the commit to exactly what telec staged for this scope;
    # anything else in the index is left alone for its owner to commit or for
    # a human to clean up. Deletions must be included so they make it in.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as msg_file:
        msg_file.write(final_message)
        msg_path = msg_file.name

    # Commit via gitpython (uses real binary, bypasses wrapper). The pre-commit
    # hook runs format and lint inside git's own atomicity. Surface git's own
    # output so callers see the commit summary and any hook output.
    repo = Repo(str(project_root))
    try:
        _, stdout, stderr = repo.git.commit("-F", msg_path, "--", *staged_for_commit, with_extended_output=True)
    except GitCommandError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        os.unlink(msg_path)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)


def _classify_main_commit(message: str, staged: list[str]) -> None:
    """Apply Path A/B/C classification for commits on main.

    Path A: all staged files non-functional + commit message contains [skip ci] → proceed.
    Path B: small functional change, human-approved → commit directly.
    Path C: functional change that warrants review → commit, then dispatch reviewer.
    """
    has_functional = any(_is_functional(f) for f in staged)

    cli_has_skip_ci = "[skip ci]" in message

    if not has_functional and cli_has_skip_ci:
        return  # Path A: autonomous non-functional commit

    # Path B/C: human gate
    print(
        "ERROR: Commits on main require classification.\n"
        "\n"
        "Inspect staged files:  git diff --staged --name-only\n"
        "\n"
        "  A) NON-FUNCTIONAL FILES ONLY (Markdown, YAML, doc snippets, state):\n"
        "     Include [skip ci] in the subject:\n"
        "       telec code commit 'chore(scope): <subject> [skip ci]'\n"
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


def _enforce_session_scope(
    staged_for_commit: list[str],
    scope_resolution: WorkspaceScopeResolution,
) -> None:
    """Block commits whose index includes files outside this session's scope.

    Stage 2 of the shared-main gate. Runs after Path A/B/C classification is
    satisfied and is independent of ``--approved``. The session scope is the
    set of files this agent's transcript touched plus any pending deletions.
    Any staged file outside that set was staged by another session (or is
    crash residue); committing it here would sweep another agent's work into
    this commit.

    No-ops when the session scope is unavailable (no transcript signal:
    integrator, fresh shell, or human manual staging) — that path is owned by
    the tolerant pre-staged fallback. ``TELECLAUDE_COMMIT_APPROVED=1`` is the
    explicit, deliberate override to commit the out-of-scope files anyway; it
    is a separate authorization from the ``--approved`` strategy flag.
    """
    scoped = set(scope_resolution.scoped_dirty_paths)
    if not scoped:
        return
    foreign = sorted(set(staged_for_commit) - scoped)
    if not foreign:
        return
    if os.environ.get("TELECLAUDE_COMMIT_APPROVED") == "1":
        return
    print("ERROR: staged files outside this session's scope:\n", file=sys.stderr)
    for path in foreign:
        print(f"  {path}", file=sys.stderr)
    own = sorted(scoped & set(staged_for_commit)) or ["<your file1>", "<your file2>"]
    print(
        "\nThese files were staged by another session. Committing them here "
        "would sweep another agent's work into this commit.\n"
        "\nIf those files are NOT yours: leave them, get human approval, then "
        "commit only your scope surgically (space-separated paths, '--' required; "
        "this commits exactly those and leaves every other staged file untouched):\n"
        "  git add -- " + " ".join(own) + "\n"
        "  TELECLAUDE_COMMIT_APPROVED=1 git commit -F <msgfile> -- " + " ".join(own) + "\n"
        "\nOr, if you deliberately intend to commit them too, re-run with the "
        "explicit scope override:\n"
        "  TELECLAUDE_COMMIT_APPROVED=1 telec code commit --approved '<message>'",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _is_functional(filepath: str) -> bool:
    """Check if a file is functional (affects runtime behavior when deployed)."""
    name = os.path.basename(filepath)
    if name in _FUNCTIONAL_NAMES:
        return True
    _, ext = os.path.splitext(name)
    return ext in _FUNCTIONAL_EXTENSIONS


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


def _check_partial_staging(project_root: Path) -> None:
    """Block commits with partially staged files."""
    repo = Repo(str(project_root))
    staged = set(repo.git.diff("--cached", "--name-only").strip().splitlines())
    unstaged = set(repo.git.diff("--name-only").strip().splitlines())
    overlap = staged & unstaged
    if overlap:
        print("ERROR: partially staged files detected.", file=sys.stderr)
        print("Pre-commit stash/restore would corrupt these files.\n", file=sys.stderr)
        for f in sorted(overlap):
            print(f"  {f}", file=sys.stderr)
        print("\nStage remaining hunks (git add -p) or use --staged.", file=sys.stderr)
        raise SystemExit(1)


def _current_branch(project_root: Path) -> str:
    """Return the current git branch name."""
    repo = Repo(str(project_root))
    branch: str = repo.git.rev_parse("--abbrev-ref", "HEAD")
    return branch.strip()

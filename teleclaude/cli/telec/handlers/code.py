"""CLI handlers for ``telec code`` namespace."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from teleclaude.cli.telec.handlers.quality import handle_format, handle_lint, handle_test
from teleclaude.cli.telec.help import _usage
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_lock import main_branch_lock
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.quality.scope import (
    is_worktree,
    resolve_project_root,
    resolve_session_scope,
)
from teleclaude.session_identity import get_system_role

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
    """List the files telec code commit would commit if invoked now.

    - Worktree: every dirty file — `git add -A` will stage them all.
    - Project root: the session transcript scope — the only source telec
      uses for staging on the project root.
    """
    _ = args
    project_root = resolve_project_root(resolve_invocation_cwd())
    if is_worktree(project_root):
        repo = Repo(str(project_root))
        status = repo.git.status("--porcelain")
        dirty = [line[3:].strip() for line in status.splitlines() if len(line) > 3]
        if not dirty:
            print("No uncommitted changes.")
            return
        for f in sorted(dirty):
            print(f)
        return

    try:
        files = resolve_session_scope(project_root)
    except RuntimeError as exc:
        print(f"ERROR: scope resolution failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not files:
        print("No session-scoped changes.")
        return
    for f in sorted(files):
        print(f)


def handle_code_commit(args: list[str]) -> None:
    """Stage the agent's session scope and commit it with a pathspec-scoped commit.

    Flags: -m <message>. Everything else passes through to git commit.

    Caller paths:
    - Outside tmux: the wrapper passes through to plain git; this command is
      not in the picture.
    - Inside tmux, autonomous agent: this command. Staging source is the
      transcript scope (worktree → all dirty). The final `git commit` runs
      with an explicit pathspec so anything else in the index (concurrent
      stage from another session, crash residue) is left untouched.
    - Inside tmux, supervised one-off: `TELECLAUDE_COMMIT_APPROVED=1 git commit -- <paths>`
      bypasses the wrapper redirect. This command is not in the picture.

    Safety primitives:
    1. Orchestrator restriction (callers in role 'orchestrator' are rejected).
    2. main-branch lock serialises all `_commit_under_lock` bodies.
    3. Pathspec on the final `git commit` scopes the commit to exactly the
       files telec staged.
    4. Pre-commit hook owns format + lint inside git's own atomicity.
    5. Path A/B/C classification on main for non-integrator, non-approved
       commits.
    """
    # Parse -m <message> and --approved, pass everything else through to git.
    # The literal "--" separator is consumed (this command appends its own
    # pathspec separator before the staged files).
    approved = "--approved" in args
    message: str | None = None
    git_args: list[str] = []
    i = 0
    filtered = [a for a in args if a not in ("--approved", "--")]
    while i < len(filtered):
        if filtered[i] == "-m" and i + 1 < len(filtered):
            message = filtered[i + 1]
            i += 2
        else:
            git_args.append(filtered[i])
            i += 1

    system_role = get_system_role()
    project_root = resolve_project_root(resolve_invocation_cwd())

    with main_branch_lock():
        _commit_under_lock(
            message=message,
            git_args=git_args,
            project_root=project_root,
            system_role=system_role,
            approved=approved,
        )


def _commit_under_lock(
    *,
    message: str | None,
    git_args: list[str],
    project_root: Path,
    system_role: str | None,
    approved: bool = False,
) -> None:
    """Execute the commit sequence while holding the main-branch lock.

    Staging policy:
    - Worktree: single-task tree, stage all dirty (`git add -A`).
    - Project root (any branch): stage the session transcript scope.

    The pre-commit hook owns format and lint inside git's own atomicity. The
    final `git commit` runs with an explicit pathspec so any other content in
    the index (concurrent stage from another session, crash residue) is not
    swept into this commit.
    """
    repo = Repo(str(project_root))
    worktree = is_worktree(project_root)
    current_branch = _current_branch(project_root)

    if worktree:
        repo.git.add("-A")
    else:
        try:
            scoped_files = resolve_session_scope(project_root)
        except RuntimeError as exc:
            print(f"ERROR: scope resolution failed: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if not scoped_files:
            print("Nothing to commit (session scope is empty).", file=sys.stderr)
            raise SystemExit(1)
        _stage_files(scoped_files, project_root)

    staged_for_commit = _get_staged_files(project_root, include_deletions=True)
    if not staged_for_commit:
        print("Nothing staged for commit.", file=sys.stderr)
        raise SystemExit(1)

    _check_partial_staging(project_root)

    # Path A/B/C classification on main
    commit_args = ["-m", message] if message else []
    commit_args.extend(git_args)

    if current_branch == "main" and system_role != "integrator" and not approved:
        # Classification looks at functional file extensions; deletions are
        # handled by including the full set with `staged_for_commit`.
        _classify_main_commit(commit_args, _get_staged_files(project_root))

    # Pathspec scopes the commit to exactly what telec staged; anything else in
    # the index (concurrent stage from another session, crash residue) is left
    # alone for its owner to commit or for a human to clean up. Deletions must
    # be included so they make it into the commit.
    commit_args.extend(["--", *staged_for_commit])

    # Commit via gitpython (uses real binary, bypasses wrapper). The pre-commit
    # hook runs format and lint inside git's own atomicity.
    try:
        repo.git.commit(*commit_args)
    except GitCommandError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def _classify_main_commit(git_args: list[str], staged: list[str]) -> None:
    """Apply Path A/B/C classification for commits on main.

    Path A: all staged files non-functional + commit message contains [skip ci] → proceed.
    Path B: small functional change, human-approved → commit directly.
    Path C: functional change that warrants review → commit, then dispatch reviewer.
    """
    has_functional = any(_is_functional(f) for f in staged)

    cli_has_skip_ci = any("[skip ci]" in a for a in git_args)

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
        "       telec code commit -m 'chore(scope): <subject> [skip ci]'\n"
        "\n"
        "  B) SMALL, SELF-EVIDENT FUNCTIONAL CHANGE (human is present):\n"
        "     State recommendation to the human, wait for approval, then:\n"
        "       telec code commit --approved -m '<type>(<scope>): <subject>'\n"
        "\n"
        "  C) FUNCTIONAL CHANGE + REVIEW:\n"
        "     Commit with human approval, then hand SHAs to a reviewer:\n"
        "       telec code commit --approved -m '<type>(<scope>): <subject>'\n"
        "     If a reviewer session is already open, reuse it:\n"
        "       telec sessions send <reviewer-session-id> 'review commits <sha1,sha2,...>'\n"
        "     Otherwise dispatch a fresh one:\n"
        "       telec sessions run --command /next-review-commits --args '<sha1,sha2,...>'"
        " --agent <agent>\n"
        "     BLOCKING: Do not proceed, end sessions, or report completion until the reviewer completes.\n"
        "     The completed turn must contain `REVIEW COMPLETE: commits ...` with a verdict.\n"
        "     Do not poll. Wait for the reviewer finished-turn notification.\n"
        "     Use the heartbeat only as the stale-notification fallback.\n"
        "     Then tail once and inspect the terminal report.\n"
        "     Commit reviews have no todo slug — do not instruct the reviewer to stamp.\n"
        "     If REQUEST CHANGES or no terminal report, fix/clarify and re-submit to the same reviewer.\n"
        "     Only `Verdict: APPROVE` closes the review gate.\n"
        "\n"
        "Explain which classification applies and why.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _is_functional(filepath: str) -> bool:
    """Check if a file is functional (affects runtime behavior when deployed)."""
    name = os.path.basename(filepath)
    if name in _FUNCTIONAL_NAMES:
        return True
    _, ext = os.path.splitext(name)
    return ext in _FUNCTIONAL_EXTENSIONS


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

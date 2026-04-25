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
from teleclaude.quality.format import FormatRunner
from teleclaude.quality.lint import LintRunner
from teleclaude.quality.scope import get_project_languages, resolve_project_root, resolve_session_scope
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
    """List session-scoped changed files (touched by this session and dirty in git)."""
    _ = args
    project_root = resolve_project_root(resolve_invocation_cwd())
    files = _resolve_scoped_files(project_root)
    if not files:
        print("No uncommitted session-scoped changes.")
        return
    for f in sorted(files):
        print(f)


def handle_code_commit(args: list[str]) -> None:
    """Stage session-scoped files, run format + lint, then commit.

    Flags: -m <message>. Everything else passes through to git commit.

    Protection model:
    1. Orchestrator restriction
    2. Main-branch lock serialization
    3. Foreign staged file detection (retryable exit)
    4. Session-scope resolution and staging
    5. Path A/B/C classification on main
    6. Format and lint staged files
    7. Commit via real git binary (bypassing wrapper)
    """
    # Parse -m <message> and --approved, pass everything else through to git
    approved = "--approved" in args
    message: str | None = None
    git_args: list[str] = []
    i = 0
    filtered = [a for a in args if a != "--approved"]
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
    """Execute the commit sequence while holding the main-branch lock."""
    # Detect foreign staged files (outside session scope)
    pre_staged = _get_staged_files(project_root)
    scoped_files = _resolve_scoped_files(project_root)
    if pre_staged:
        scoped_set = set(scoped_files)
        foreign = [f for f in pre_staged if f not in scoped_set]
        if foreign:
            print(
                "ERROR: Staged files outside your session scope detected — another agent may be mid-commit.\n",
                file=sys.stderr,
            )
            for f in foreign:
                print(f"  {f}", file=sys.stderr)
            print(
                "\nUnstage with: git reset HEAD -- <file>\nOr wait for the other agent to finish and retry.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    # Session-scope resolution → stage files
    if scoped_files:
        _stage_files(scoped_files, project_root)

    staged = _get_staged_files(project_root)
    if not staged:
        print("Nothing staged for commit.", file=sys.stderr)
        raise SystemExit(1)

    _check_partial_staging(project_root)

    # Path A/B/C classification on main
    commit_args = ["-m", message] if message else []
    commit_args.extend(git_args)

    current_branch = _current_branch(project_root)
    if current_branch == "main" and system_role != "integrator" and not approved:
        _classify_main_commit(commit_args, staged)

    # Format staged files; the pre-commit hook owns formatter restaging/retry.
    languages = get_project_languages(project_root)
    runner = FormatRunner(project_root=project_root, languages=languages)
    runner.run(files=staged)

    # Lint staged files
    lint_runner = LintRunner(project_root=project_root)
    lint_runner.run(files=staged)

    # Commit via gitpython (uses real binary, bypasses wrapper)
    repo = Repo(str(project_root))
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
        "     BLOCKING: Do not proceed, end sessions, or report completion until the\n"
        "     reviewer outputs a verdict. Tail the reviewer session for the verdict.\n"
        "     Commit reviews have no todo slug — do not instruct the reviewer to stamp.\n"
        "     If REQUEST CHANGES, fix and re-submit to the same reviewer.\n"
        "     Only an APPROVE verdict closes the review gate.\n"
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


def _resolve_scoped_files(project_root: str | Path) -> list[str]:
    """Resolve session-scoped files for staging."""
    try:
        return resolve_session_scope(Path(project_root) if isinstance(project_root, str) else project_root)
    except RuntimeError:
        return []


def _stage_files(files: list[str], project_root: Path) -> None:
    """Stage files via git add."""
    repo = Repo(str(project_root))
    repo.git.add("--", *files)


def _get_staged_files(project_root: Path) -> list[str]:
    """Return list of staged file paths."""
    repo = Repo(str(project_root))
    output: str = repo.git.diff("--cached", "--name-only", "--diff-filter=ACM")
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

"""Git smudge/clean filter setup for tilde expansion.

The ``teleclaude-docs`` filter expands ``@~/.teleclaude`` to ``@$HOME/.teleclaude``
on checkout (smudge) and contracts it back on commit (clean). The filter *driver*
lives in ``.git/config`` — which is per-clone and never committed — so a fresh
clone has the ``.gitattributes`` rule but no driver, and smudge silently no-ops.

``ensure_git_filters`` is the self-healing entry point: it (re)installs the driver
and force re-smudges any already-checked-out files that are still unexpanded, so an
existing checkout converges to a working state on every ``telec sync``.
"""

from pathlib import Path

from teleclaude.git import GitCommandError, Repo

# The portable token written to disk by the clean filter (and present in any
# checkout where smudge never ran). Detecting it identifies stale files.
PRE_SMUDGE_TOKEN = "@~/.teleclaude"

# The filter only ever applies under docs/ (see .gitattributes and
# gitattributes.FILTER_PATTERNS). Scoping the working-tree scan here keeps it
# fast — it skips the rest of the tracked tree — and states the intent plainly.
_FILTER_SCOPE = "docs"


def ensure_git_filters(project_root: Path) -> None:
    """Configure the filter driver and re-smudge stale files (self-healing).

    Idempotent and CI-safe. Installs the driver into ``.git/config`` and re-runs
    smudge on filtered files that are unmodified yet still hold the pre-smudge
    token. Locally modified files are left untouched to avoid clobbering edits.

    Args:
        project_root: Path to the project root directory.
    """
    if not (project_root / ".git").exists():
        print("git_filters: not a git repository, skipping filter setup.")
        return

    repo = Repo(project_root)
    _configure_filter_driver(repo)
    restored = _force_resmudge(repo, project_root)
    if restored:
        print(f"git_filters: re-smudged {restored} file(s) to absolute paths.")
    else:
        print("git_filters: filter driver configured; working tree already smudged.")


def setup_git_filters(project_root: Path) -> None:
    """Configure git smudge/clean filters for tilde expansion (config only).

    - Smudge: Expands @~/.teleclaude to @$HOME/.teleclaude on checkout
    - Clean: Converts @$HOME/.teleclaude back to @~/.teleclaude on commit

    Args:
        project_root: Path to the project root directory.
    """
    if not (project_root / ".git").exists():
        print("git_filters: not a git repository, skipping filter setup.")
        return

    repo = Repo(project_root)
    _configure_filter_driver(repo)
    print("git_filters: configured smudge/clean filters for tilde expansion.")


def _configure_filter_driver(repo: Repo) -> None:
    """Install the teleclaude-docs filter driver into the repo's git config."""
    home = str(Path.home())
    smudge_cmd = f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'
    clean_cmd = f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'

    _run_git_config(repo, "filter.teleclaude-docs.smudge", smudge_cmd)
    _run_git_config(repo, "filter.teleclaude-docs.clean", clean_cmd)
    _run_git_config(repo, "filter.teleclaude-docs.required", "true")


def _force_resmudge(repo: Repo, project_root: Path) -> int:
    """Re-run smudge on filtered files that are clean but still unexpanded.

    Returns the number of files restored. Candidates are found by grepping the
    working tree for the pre-smudge token (cheap, narrows to a handful), then
    confirmed against the resolved ``filter`` attribute so files that legitimately
    keep the token (``-filter`` overrides) are left alone. Locally modified files
    are skipped to avoid clobbering edits. Deleting and re-checking out the rest
    re-runs the smudge filter.
    """
    token_files = _files_with_token(repo)
    if not token_files:
        return 0

    matched = _filter_matched(repo, token_files)
    stale = sorted(set(matched) - _modified_files(repo))
    if not stale:
        return 0

    for relative_path in stale:
        (project_root / relative_path).unlink()
    repo.git.checkout("--", *stale)
    return len(stale)


def _files_with_token(repo: Repo) -> list[str]:
    """Return tracked docs files whose working-tree content holds the pre-smudge token.

    NUL-framed (``-z``) like the check-attr scan below, so paths are split on NUL
    rather than newlines — robust to any character in a tracked path.
    """
    try:
        listed: str = repo.git.grep("-l", "-z", "-F", PRE_SMUDGE_TOKEN, "--", _FILTER_SCOPE)
    except GitCommandError as exc:
        if exc.status == 1:  # git grep exits 1 when nothing matches
            return []
        raise
    return [path for path in listed.split("\0") if path]


def _filter_matched(repo: Repo, paths: list[str]) -> list[str]:
    """Return the subset of ``paths`` whose resolved ``filter`` attribute is teleclaude-docs."""
    if not paths:
        return []

    raw = repo.git.check_attr("filter", "-z", "--", *paths)
    fields = raw.split("\0")
    matched: list[str] = []
    for index in range(0, len(fields) - 2, 3):
        path, _attr, value = fields[index], fields[index + 1], fields[index + 2]
        if value == "teleclaude-docs":
            matched.append(path)
    return matched


def _modified_files(repo: Repo) -> set[str]:
    """Return tracked files with staged or unstaged local modifications."""
    unstaged = repo.git.diff("--name-only").splitlines()
    staged = repo.git.diff("--cached", "--name-only").splitlines()
    return set(unstaged) | set(staged)


def _run_git_config(repo: Repo, key: str, value: str) -> None:
    """Run git config command."""
    repo.git.config(key, value)

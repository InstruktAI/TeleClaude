"""Git smudge/clean filter setup for tilde expansion."""

from pathlib import Path

from teleclaude.git import Repo


def setup_git_filters(project_root: Path) -> None:
    """Configure git smudge/clean filters for tilde expansion.

    - Smudge: Expands @~/.teleclaude to @$HOME/.teleclaude on checkout
    - Clean: Converts @$HOME/.teleclaude back to @~/.teleclaude on commit

    Args:
        project_root: Path to the project root directory.
    """
    git_dir = project_root / ".git"
    if not git_dir.exists():
        print("telec init: not a git repository, skipping filter setup.")
        return

    repo = Repo(project_root)
    home = str(Path.home())
    smudge_cmd = f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'
    clean_cmd = f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'

    _run_git_config(repo, "filter.teleclaude-docs.smudge", smudge_cmd)
    _run_git_config(repo, "filter.teleclaude-docs.clean", clean_cmd)
    _run_git_config(repo, "filter.teleclaude-docs.required", "true")

    print("telec init: git filters configured.")


def _run_git_config(repo: Repo, key: str, value: str) -> None:
    """Run git config command."""
    repo.git.config(key, value)

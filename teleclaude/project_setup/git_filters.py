"""Git smudge/clean filter setup for tilde expansion."""

import subprocess
from pathlib import Path


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

    home = str(Path.home())
    smudge_cmd = f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'
    clean_cmd = f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'

    _run_git_config(project_root, "filter.teleclaude-docs.smudge", smudge_cmd)
    _run_git_config(project_root, "filter.teleclaude-docs.clean", clean_cmd)
    _run_git_config(project_root, "filter.teleclaude-docs.required", "true")

    _recheckout_docs(project_root)
    print("telec init: git filters configured.")


def _run_git_config(project_root: Path, key: str, value: str) -> None:
    """Run git config command."""
    subprocess.run(
        ["git", "config", key, value],
        cwd=project_root,
        check=True,
        capture_output=True,
    )


def _recheckout_docs(project_root: Path) -> None:
    """Re-checkout docs to apply smudge filter to existing files."""
    docs_paths = ["docs/", "agents/docs/"]
    for doc_path in docs_paths:
        if (project_root / doc_path).exists():
            subprocess.run(
                ["git", "checkout", "--", doc_path],
                cwd=project_root,
                check=False,
                capture_output=True,
            )

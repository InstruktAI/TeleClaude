"""Git hook deployment for project setup."""

import subprocess
from pathlib import Path

from teleclaude.git import GIT_EXECUTABLE

_PRECOMMIT_SOURCE = Path(".githooks") / "pre-commit"
_POSTMERGE_SOURCE = Path(".githooks") / "post-merge"


def _hook_destination(project_root: Path, hook_name: str) -> Path:
    result = subprocess.run(
        [GIT_EXECUTABLE, "rev-parse", "--git-path", f"hooks/{hook_name}"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        path = Path(result.stdout.strip())
        if not path.is_absolute():
            path = project_root / path
        return path
    return project_root / ".git" / "hooks" / hook_name


def _install_hook(project_root: Path, *, hook_name: str, source_path: Path) -> None:
    source = project_root / source_path
    destination = _hook_destination(project_root, hook_name)

    if not source.exists():
        print(f"telec projects init: {hook_name} hook source not found at {source}.")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    destination.chmod(destination.stat().st_mode | 0o111)
    print(f"telec projects init: thin {hook_name} hook installed.")


def install_precommit_hook(project_root: Path) -> None:
    """Install the project-owned thin pre-commit hook source into ``.git/hooks``."""
    _install_hook(project_root, hook_name="pre-commit", source_path=_PRECOMMIT_SOURCE)


def install_postmerge_hook(project_root: Path) -> None:
    """Install the project-owned thin post-merge hook source into ``.git/hooks``."""
    _install_hook(project_root, hook_name="post-merge", source_path=_POSTMERGE_SOURCE)

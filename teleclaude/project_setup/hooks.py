"""Git hook deployment for project setup."""

import subprocess
from pathlib import Path

from teleclaude.git import GIT_EXECUTABLE

_PRECOMMIT_SOURCE = Path(".githooks") / "pre-commit"


def _hook_destination(project_root: Path) -> Path:
    result = subprocess.run(
        [GIT_EXECUTABLE, "rev-parse", "--git-path", "hooks/pre-commit"],
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
    return project_root / ".git" / "hooks" / "pre-commit"


def install_precommit_hook(project_root: Path) -> None:
    """Install the project-owned thin pre-commit hook source into ``.git/hooks``."""
    source = project_root / _PRECOMMIT_SOURCE
    destination = _hook_destination(project_root)

    if not source.exists():
        print(f"telec projects init: pre-commit hook source not found at {source}.")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    destination.chmod(destination.stat().st_mode | 0o111)
    print("telec projects init: thin pre-commit hook installed.")

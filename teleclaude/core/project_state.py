"""Workflow-owned resolution of checkout-backed shared project state."""

from __future__ import annotations

from pathlib import Path

from teleclaude.paths import ConfigFileName

_GIT_DIRNAME = ".git"
_GITDIR_PREFIX = "gitdir:"
_CHECKOUT_ERROR = "cwd does not resolve to a project checkout: {path}"


def resolve_project_state_root(start: str | Path) -> Path:
    """Return the owning checkout for a project or linked worktree."""
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    original = current
    while current != current.parent:
        git_path = current / _GIT_DIRNAME
        if git_path.is_dir():
            return _require_project_config(current, original)
        if git_path.is_file():
            try:
                content = git_path.read_text().strip()
            except OSError as exc:
                raise FileNotFoundError(_CHECKOUT_ERROR.format(path=original)) from exc
            if content.startswith(_GITDIR_PREFIX):
                gitdir = Path(content.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (current / gitdir).resolve()
                for parent in gitdir.parents:
                    if parent.name == _GIT_DIRNAME:
                        return _require_project_config(parent.parent, original)
            raise FileNotFoundError(_CHECKOUT_ERROR.format(path=original))
        current = current.parent
    raise FileNotFoundError(_CHECKOUT_ERROR.format(path=original))


def _require_project_config(root: Path, original: Path) -> Path:
    if not (root / ConfigFileName.OVERLAY).exists():
        raise FileNotFoundError(_CHECKOUT_ERROR.format(path=original))
    return root

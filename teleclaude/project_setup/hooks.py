"""Git hook deployment for project setup."""

from pathlib import Path

from teleclaude.git import GitCommandError, Repo

_HOOK_TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[2] / "templates" / "quality" / "githooks"
_PRECOMMIT_NAME = "pre-commit"
_POSTMERGE_NAME = "post-merge"
_PREPUSH_NAME = "pre-push"
_PRECOMMIT_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _PRECOMMIT_NAME
_POSTMERGE_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _POSTMERGE_NAME
_PREPUSH_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _PREPUSH_NAME
_TELECLAUDE_SENTINEL = b"# teleclaude:"
_GIT_PATH_ARGUMENT = "--git-path"
_HOOK_PATH_TEMPLATE = "hooks/{hook_name}"
_HOOK_MISSING_MESSAGE = "telec projects init: {hook_name} hook source not found at {source}."
_HOOK_PRESERVED_MESSAGE = "telec projects init: existing {hook_name} hook preserved."
_HOOK_INSTALLED_MESSAGE = "telec projects init: thin {hook_name} hook installed."


def _hook_destination(project_root: Path, hook_name: str) -> Path:
    repo = Repo(project_root)
    try:
        path = Path(repo.git.rev_parse(_GIT_PATH_ARGUMENT, _HOOK_PATH_TEMPLATE.format(hook_name=hook_name)))
        if not path.is_absolute():
            path = project_root / path
        return path
    except GitCommandError:
        return project_root / ".git" / "hooks" / hook_name


def _install_hook(project_root: Path, *, hook_name: str, source_path: Path) -> None:
    source = source_path
    destination = _hook_destination(project_root, hook_name)

    if not source.exists():
        print(_HOOK_MISSING_MESSAGE.format(hook_name=hook_name, source=source))
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_content = source.read_bytes()
    if destination.exists() and _TELECLAUDE_SENTINEL not in destination.read_bytes():
        print(_HOOK_PRESERVED_MESSAGE.format(hook_name=hook_name))
        return
    destination.write_bytes(source_content)
    destination.chmod(destination.stat().st_mode | 0o111)
    print(_HOOK_INSTALLED_MESSAGE.format(hook_name=hook_name))


def install_precommit_hook(project_root: Path) -> None:
    """Install the project-owned thin pre-commit hook source into ``.git/hooks``."""
    _install_hook(project_root, hook_name=_PRECOMMIT_NAME, source_path=_PRECOMMIT_SOURCE)


def install_postmerge_hook(project_root: Path) -> None:
    """Install the project-owned thin post-merge hook source into ``.git/hooks``."""
    _install_hook(project_root, hook_name=_POSTMERGE_NAME, source_path=_POSTMERGE_SOURCE)


def install_code_hooks(project_root: Path) -> None:
    """Install the capability-owned hook set from its canonical templates."""
    for hook_name, source_path in (
        (_PRECOMMIT_NAME, _PRECOMMIT_SOURCE),
        (_POSTMERGE_NAME, _POSTMERGE_SOURCE),
        (_PREPUSH_NAME, _PREPUSH_SOURCE),
    ):
        _install_hook(project_root, hook_name=hook_name, source_path=source_path)

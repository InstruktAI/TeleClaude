"""Git hook deployment for project setup."""

from enum import StrEnum
from pathlib import Path

from teleclaude.git import GitCommandError, Repo

_HOOK_TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[2] / "templates" / "quality" / "githooks"
_PRECOMMIT_NAME = "pre-commit"
_POSTCOMMIT_NAME = "post-commit"
_POSTMERGE_NAME = "post-merge"
_PREPUSH_NAME = "pre-push"
_PRECOMMIT_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _PRECOMMIT_NAME
_POSTCOMMIT_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _POSTCOMMIT_NAME
_POSTMERGE_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _POSTMERGE_NAME
_PREPUSH_SOURCE = _HOOK_TEMPLATE_DIRECTORY / _PREPUSH_NAME
_TELECLAUDE_SENTINEL = b"# teleclaude:"
_GIT_PATH_ARGUMENT = "--git-path"
_HOOK_PATH_TEMPLATE = "hooks/{hook_name}"
_HOOK_MISSING_MESSAGE = "teleclaude hooks: {hook_name} hook source not found at {source}."
_HOOK_PRESERVED_MESSAGE = "teleclaude hooks: existing {hook_name} hook preserved."
_HOOK_INSTALLED_MESSAGE = "teleclaude hooks: thin {hook_name} hook installed."
_HOOK_UNCHANGED_MESSAGE = "teleclaude hooks: existing {hook_name} hook already matches."


class HookConvergenceOutcome(StrEnum):
    """Terminal disposition for one managed hook template."""

    WRITTEN = "written"
    UNCHANGED = "unchanged"
    PRESERVED = "preserved"
    TEMPLATE_MISSING = "template_missing"


def _hook_destination(project_root: Path, hook_name: str) -> Path:
    repo = Repo(project_root)
    try:
        path = Path(repo.git.rev_parse(_GIT_PATH_ARGUMENT, _HOOK_PATH_TEMPLATE.format(hook_name=hook_name)))
        if not path.is_absolute():
            path = project_root / path
        return path
    except GitCommandError:
        return project_root / ".git" / "hooks" / hook_name


def _install_hook(
    project_root: Path,
    *,
    hook_name: str,
    source_path: Path,
) -> HookConvergenceOutcome:
    source = source_path
    destination = _hook_destination(project_root, hook_name)

    if not source.exists():
        print(_HOOK_MISSING_MESSAGE.format(hook_name=hook_name, source=source))
        return HookConvergenceOutcome.TEMPLATE_MISSING

    source_content = source.read_bytes()
    if destination.exists():
        destination_content = destination.read_bytes()
        if _TELECLAUDE_SENTINEL not in destination_content:
            print(_HOOK_PRESERVED_MESSAGE.format(hook_name=hook_name))
            return HookConvergenceOutcome.PRESERVED
        if destination_content == source_content:
            print(_HOOK_UNCHANGED_MESSAGE.format(hook_name=hook_name))
            return HookConvergenceOutcome.UNCHANGED

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source_content)
    destination.chmod(destination.stat().st_mode | 0o111)
    print(_HOOK_INSTALLED_MESSAGE.format(hook_name=hook_name))
    return HookConvergenceOutcome.WRITTEN


def install_code_hooks(project_root: Path) -> dict[str, HookConvergenceOutcome]:
    """Install the capability-owned hook set from its canonical templates."""
    outcomes: dict[str, HookConvergenceOutcome] = {}
    for hook_name, source_path in (
        (_PRECOMMIT_NAME, _PRECOMMIT_SOURCE),
        (_POSTCOMMIT_NAME, _POSTCOMMIT_SOURCE),
        (_POSTMERGE_NAME, _POSTMERGE_SOURCE),
        (_PREPUSH_NAME, _PREPUSH_SOURCE),
    ):
        outcomes[hook_name] = _install_hook(project_root, hook_name=hook_name, source_path=source_path)
    return outcomes

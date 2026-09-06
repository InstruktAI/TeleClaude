"""Project capability projection into TeleClaude-owned git metadata."""

from __future__ import annotations

from pathlib import Path

from teleclaude.capabilities import Capabilities, CapabilityName, resolve_capabilities, resolve_tier_permissions
from teleclaude.git import InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import ConfigFileName

_MARKER_DIRECTORY = Path("teleclaude") / "capabilities"
_ONBOARDED_MARKER = "onboarded"
_INVOCATION_CONTEXT_MARKER = "invocation-context"
_GIT_COMMON_DIRECTORY_ARGUMENT = "--git-common-dir"


def _common_git_directory(project_root: Path) -> Path | None:
    """Resolve repository-wide git metadata shared by every linked worktree."""
    try:
        repo = Repo(project_root)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return None
    raw_path = Path(repo.git.rev_parse(_GIT_COMMON_DIRECTORY_ARGUMENT))
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (project_root / raw_path).resolve()


def capability_marker_directory(project_root: Path) -> Path | None:
    """Return the TeleClaude-owned capability marker directory."""
    common_directory = _common_git_directory(project_root)
    return common_directory / _MARKER_DIRECTORY if common_directory is not None else None


def project_capabilities(project_root: Path) -> Capabilities:
    """Project the declaration into idempotent repository-wide markers."""
    capabilities = resolve_capabilities(project_root)
    marker_directory = capability_marker_directory(project_root)
    if marker_directory is None:
        return capabilities
    marker_directory.mkdir(parents=True, exist_ok=True)
    invocation_marker = marker_directory / _INVOCATION_CONTEXT_MARKER
    if (project_root / ConfigFileName.OVERLAY).is_file():
        permissions = resolve_tier_permissions(project_root)
        if permissions.invocation_context and not permissions.project_subscriptions.is_target:
            invocation_marker.touch(exist_ok=True)
        elif invocation_marker.exists():
            invocation_marker.unlink()
    if not capabilities.is_target:
        return capabilities
    onboarded_marker = marker_directory / _ONBOARDED_MARKER
    if not onboarded_marker.exists():
        onboarded_marker.touch()

    subscriptions = {
        CapabilityName.CODE: capabilities.code,
        CapabilityName.DOCS: capabilities.docs,
        CapabilityName.AGENTS: capabilities.agents,
    }
    for name, enabled in subscriptions.items():
        marker_path = marker_directory / name.value
        if enabled and not marker_path.exists():
            marker_path.touch()
        elif not enabled and marker_path.exists():
            marker_path.unlink()

    return capabilities

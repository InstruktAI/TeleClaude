"""Record the landed paths and checkpoint state for a successful sealed commit."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from teleclaude.cli.telec.handlers._code_commit_guidance import _NON_CODE_DOCUMENTATION_PATTERNS
from teleclaude.cli.telec.handlers._code_git_state import resolve_current_branch
from teleclaude.git import GitCommandError, Repo
from teleclaude.hooks.checkpoint_flags import record_authored_main_commit
from teleclaude.session_identity import get_session_id

_GIT_SHOW_NAME_ONLY = "--name-only"
_GIT_SHOW_FORMAT = "--format="
_GIT_HEAD = "HEAD"
_MAIN_BRANCH = "main"


def record_commit_success(repo: Repo, project_root: Path, fallback_paths: list[str]) -> list[str]:
    """Resolve committed paths and record their main-branch checkpoint marker."""
    try:
        committed_files = [
            path for path in repo.git.show(_GIT_SHOW_NAME_ONLY, _GIT_SHOW_FORMAT, _GIT_HEAD).splitlines() if path
        ]
    except GitCommandError:
        committed_files = list(fallback_paths)

    session_id = get_session_id()
    current_branch = resolve_current_branch(project_root)
    committed_includes_code = any(
        not any(fnmatch(path, pattern) for pattern in _NON_CODE_DOCUMENTATION_PATTERNS) for path in committed_files
    )
    if current_branch == _MAIN_BRANCH and committed_includes_code and session_id:
        record_authored_main_commit(session_id)
    return committed_files

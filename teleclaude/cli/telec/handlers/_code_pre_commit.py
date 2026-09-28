"""Thin pre-commit hook backstop routed through the typed CLI."""

from __future__ import annotations

import sys

from teleclaude.cli.telec.handlers._code_git_state import working_tree_snapshot
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.project_root import resolve_invocation_roots

_CACHED = "--cached"
_DIFF_FILTER_ACMR = "--diff-filter=ACMR"
_NAME_ONLY = "--name-only"
_NUL = "-z"
_NUL_CHARACTER = "\x00"
_PARTIAL_STAGING_ERROR = "ERROR: partially staged files detected:"
_PRE_COMMIT_GIT_ERROR = "ERROR: pre-commit safety check failed: {error}"
_PRE_COMMIT_USAGE = "Usage: telec code pre-commit"
_RESTAGE_INSTRUCTION = "Fully restage via: telec code add <file>"
_PATH_PREFIX = "  "
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, ValueError)


def handle_code_pre_commit(args: list[str]) -> None:
    """Fail closed when the hook-visible checkout has partial staging."""
    if args:
        print(_PRE_COMMIT_USAGE, file=sys.stderr)
        raise SystemExit(2)
    project_root = resolve_invocation_roots().repository_root
    try:
        repo = Repo(str(project_root))
        snapshot = working_tree_snapshot(project_root)
        candidates = frozenset(
            path for path in repo.git.diff(_CACHED, _NAME_ONLY, _DIFF_FILTER_ACMR, _NUL).split(_NUL_CHARACTER) if path
        )
    except _GIT_FAILURES as exc:
        print(_PRE_COMMIT_GIT_ERROR.format(error=exc), file=sys.stderr)
        raise SystemExit(1) from exc
    partial_staged = sorted(snapshot.partial_staged & candidates)
    if not partial_staged:
        return
    print(_PARTIAL_STAGING_ERROR, file=sys.stderr)
    for path in partial_staged:
        print(_PATH_PREFIX + path, file=sys.stderr)
    print(_RESTAGE_INSTRUCTION, file=sys.stderr)
    raise SystemExit(1)

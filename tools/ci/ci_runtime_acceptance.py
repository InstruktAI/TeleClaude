"""Run full runtime acceptance against one unchanged checkout revision."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.ci import runtime_acceptance

_GIT_EXECUTABLE = "git"
_GIT_COMMAND_TIMEOUT_SECONDS = 30
_HEAD_REVISION_ARGUMENTS = ("rev-parse", "HEAD")
_HEAD_TREE_ARGUMENTS = ("rev-parse", "HEAD^{tree}")
_UNSTAGED_DIFF_ARGUMENTS = ("diff", "--exit-code")
_STAGED_DIFF_ARGUMENTS = ("diff", "--cached", "--exit-code")
_UNTRACKED_ARGUMENTS = ("ls-files", "--others", "--exclude-standard")
_ROOT_OPTION = "--root"
_REPORT_OPTION = "--report"
_PROFILE_OPTION = "--profile"
_SOURCE_REVISION_OPTION = "--source-revision"
_SOURCE_TREE_OPTION = "--source-tree"
_PROFILE_FULL = "full"
_SOURCE_CHANGED_ERROR = "The checkout changed while runtime acceptance was running."
_GIT_COMMAND_ERROR = "Git could not inspect the runtime acceptance checkout: {detail}"
_PROFILE_ERROR = "Runtime acceptance failed with exit status {status}."


def _run_git(root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a bounded Git observation because Git is the checkout's source of truth."""
    try:
        return subprocess.run(
            (_GIT_EXECUTABLE, *arguments),
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(_GIT_COMMAND_ERROR.format(detail=error)) from error


def _git_text(root: Path, arguments: Sequence[str]) -> str:
    result = _run_git(root, arguments)
    if result.returncode != 0:
        raise RuntimeError(_GIT_COMMAND_ERROR.format(detail=result.stderr.strip()))
    return result.stdout.strip()


def _verify_checkout(root: Path, source_revision: str, source_tree: str) -> None:
    observed_revision = _git_text(root, _HEAD_REVISION_ARGUMENTS)
    observed_tree = _git_text(root, _HEAD_TREE_ARGUMENTS)
    unstaged = _run_git(root, _UNSTAGED_DIFF_ARGUMENTS)
    staged = _run_git(root, _STAGED_DIFF_ARGUMENTS)
    untracked = _git_text(root, _UNTRACKED_ARGUMENTS)
    if (
        observed_revision != source_revision
        or observed_tree != source_tree
        or unstaged.returncode != 0
        or staged.returncode != 0
        or untracked
    ):
        raise RuntimeError(_SOURCE_CHANGED_ERROR)


def _parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_ROOT_OPTION, type=Path, required=True)
    parser.add_argument(_REPORT_OPTION, type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run full acceptance, then require the source checkout to remain unchanged."""
    parsed = _parse_arguments(arguments)
    root = parsed.root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"The checkout root is not a directory: {root}")
    source_revision = _git_text(root, _HEAD_REVISION_ARGUMENTS)
    source_tree = _git_text(root, _HEAD_TREE_ARGUMENTS)
    profile_status = 1
    profile_error: Exception | None = None
    try:
        profile_status = runtime_acceptance.main(
            [
                _PROFILE_OPTION,
                _PROFILE_FULL,
                _ROOT_OPTION,
                str(root),
                _SOURCE_REVISION_OPTION,
                source_revision,
                _SOURCE_TREE_OPTION,
                source_tree,
                _REPORT_OPTION,
                str(parsed.report.expanduser().resolve()),
            ]
        )
    except Exception as error:
        profile_error = error

    checkout_error: Exception | None = None
    try:
        _verify_checkout(root, source_revision, source_tree)
    except Exception as error:
        checkout_error = error

    if profile_error is not None:
        print(str(profile_error), file=sys.stderr)
    if checkout_error is not None:
        print(str(checkout_error), file=sys.stderr)
    if profile_status != 0:
        print(_PROFILE_ERROR.format(status=profile_status), file=sys.stderr)
    return int(profile_error is not None or checkout_error is not None or profile_status != 0)


if __name__ == "__main__":
    raise SystemExit(main())

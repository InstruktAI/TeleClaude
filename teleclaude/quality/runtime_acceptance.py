"""Run cold runtime acceptance once for this repository's prospective commit tree."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Final

from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.runtime.command_runner import run_process_group_command

_CONTROLLER_RELATIVE_PATH = Path("tools") / "ci" / "runtime_acceptance.py"
_PYTHON_SAFE_PATH_OPTION = "-P"
_PROFILE_OPTION = "--profile"
_PROFILE_COLD = "cold"
_ROOT_OPTION = "--root"
_SOURCE_REVISION_OPTION = "--source-revision"
_SOURCE_TREE_OPTION = "--source-tree"
_REPORT_OPTION = "--report"
_REPORT_DIRECTORY = "teleclaude-runtime-acceptance-reports"
_REPORT_FILENAME_TEMPLATE = "cold-{tree}.json"
_UNBORN_REVISION = "unborn"
_COMMAND_TIMEOUT_SECONDS = 480
_PATH_VARIABLE = "PATH"
_LANG_VARIABLE = "LANG"
_TMP_VARIABLE = "TMPDIR"
_PYTHONPATH_VARIABLE = "PYTHONPATH"
_PYTHONDONTWRITEBYTECODE_VARIABLE = "PYTHONDONTWRITEBYTECODE"
_PYTHONNOUSERSITE_VARIABLE = "PYTHONNOUSERSITE"
_GIT_CONFIG_GLOBAL_VARIABLE = "GIT_CONFIG_GLOBAL"
_GIT_CONFIG_SYSTEM_VARIABLE = "GIT_CONFIG_SYSTEM"
_GIT_CONFIG_NOSYSTEM_VARIABLE = "GIT_CONFIG_NOSYSTEM"
_TRUE_TEXT = "1"
_DEFAULT_LOCALE = "C.UTF-8"
_SOURCE_TREE_PLACEHOLDER = "<source-tree>"
_COMMIT_GATE_FAILURE = "Cold CLI runtime acceptance failed for active-index tree {tree} (exit {exit_code})."
_COMMIT_GATE_SUCCESS = "Cold CLI runtime acceptance passed for active-index tree {tree}."
_REPOSITORY_IDENTITY_UNAVAILABLE = "Could not establish the repository identity for runtime acceptance."
_IDENTITY_FAILURES = (BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)
_GIT_COMMON_DIRECTORY_ARGUMENTS: Final[tuple[str, ...]] = ("--git-common-dir",)
_GIT_HEAD_ARGUMENTS: Final[tuple[str, ...]] = ("--verify", "HEAD")


def is_self_repository(project_root: Path, installation_root: Path) -> bool:
    """Match the repository's shared Git common directory, including linked worktrees."""
    try:
        return _common_git_directory(project_root) == _common_git_directory(installation_root)
    except _IDENTITY_FAILURES as exc:
        raise ValueError(_REPOSITORY_IDENTITY_UNAVAILABLE) from exc


def run_cold_commit_acceptance(
    source_root: Path,
    source_revision: str,
    source_tree: str,
) -> int:
    """Run the candidate controller and return its blocking exit status."""
    controller = source_root / _CONTROLLER_RELATIVE_PATH
    report_path = Path(tempfile.gettempdir()) / _REPORT_DIRECTORY / _REPORT_FILENAME_TEMPLATE.format(tree=source_tree)
    command = [
        sys.executable,
        _PYTHON_SAFE_PATH_OPTION,
        str(controller),
        _PROFILE_OPTION,
        _PROFILE_COLD,
        _ROOT_OPTION,
        str(source_root),
        _SOURCE_REVISION_OPTION,
        source_revision,
        _SOURCE_TREE_OPTION,
        source_tree,
        _REPORT_OPTION,
        str(report_path),
    ]
    child_environment = _controller_environment(source_root)
    result = run_process_group_command(
        command,
        source_root,
        child_environment,
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        capture_output=lambda output: output.replace(str(source_root), _SOURCE_TREE_PLACEHOLDER),
        nested_runner=True,
    )
    if result.exit_code == 0:
        print(_COMMIT_GATE_SUCCESS.format(tree=source_tree))
        return 0
    print(
        _COMMIT_GATE_FAILURE.format(tree=source_tree, exit_code=result.exit_code),
        file=sys.stderr,
    )
    if result.output_tail:
        print(result.output_tail, file=sys.stderr)
    print(f"Report: {report_path}", file=sys.stderr)
    return result.exit_code


def active_index_identity(project_root: Path) -> tuple[str, str]:
    """Return the current HEAD and exact active-index tree identities."""
    repo = Repo(str(project_root))
    try:
        revision = repo.git.rev_parse(*_GIT_HEAD_ARGUMENTS).strip()
    except _IDENTITY_FAILURES:
        revision = _UNBORN_REVISION
    tree = repo.git.write_tree().strip()
    return revision or _UNBORN_REVISION, tree


def _common_git_directory(repository_root: Path) -> Path:
    """Resolve Git's shared directory for a checkout or linked worktree."""
    repo = Repo(str(repository_root))
    working_tree = repo.working_tree_dir
    if working_tree is None:
        raise ValueError(_REPOSITORY_IDENTITY_UNAVAILABLE)
    value = repo.git.rev_parse(*_GIT_COMMON_DIRECTORY_ARGUMENTS).strip()
    common_directory = Path(value)
    if not common_directory.is_absolute():
        common_directory = Path(working_tree) / common_directory
    return common_directory.resolve()


def _controller_environment(source_root: Path) -> dict[str, str]:
    """Pass only process-launch inputs; the controller creates its own synthetic runtime state."""
    host_environment = os.environ  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    child_environment = {
        _PATH_VARIABLE: host_environment.get(_PATH_VARIABLE, ""),
        _LANG_VARIABLE: host_environment.get(_LANG_VARIABLE, _DEFAULT_LOCALE),
        _TMP_VARIABLE: tempfile.gettempdir(),
        _PYTHONDONTWRITEBYTECODE_VARIABLE: _TRUE_TEXT,
        _PYTHONNOUSERSITE_VARIABLE: _TRUE_TEXT,
        _PYTHONPATH_VARIABLE: str(source_root),
        _GIT_CONFIG_GLOBAL_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_VARIABLE: os.devnull,
        _GIT_CONFIG_NOSYSTEM_VARIABLE: _TRUE_TEXT,
    }
    return child_environment

"""Prepare a release of the installation as a full build while the daemon serves.

The installation keeps one repository of its source, cloned once. A release is a detached worktree of
that repository at one revision, with its own environment built in place — the locked Python
environment and the Discord voice bridge — so it runs on its own and depends on no project checkout.
Preparation touches nothing live: a failed attempt leaves no partial release behind and the active
release keeps serving. This module executes git operations and builds; it decides nothing about which
revision to install (``reconciliation.install_act``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.git import BadName, GitCommandError, Repo

logger = get_logger(__name__)

_REMOTE_NAME = "origin"
_FETCH_CONFIG_KEY = "remote.origin.fetch"
_FETCH_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"
_FETCH_ARGUMENTS = ("--tags", "--prune", _REMOTE_NAME)
_VENV_DIRECTORY = ".venv"
_BUILT_MARKER = ".release-built"
_VOICE_BRIDGE_PATH = Path("teleclaude") / "adapters" / "discord" / "voice_bridge"
_VOICE_BRIDGE_OUTPUT = "dist"
_UV_EXECUTABLE = "uv"
_UV_FALLBACK = Path(".local") / "bin" / _UV_EXECUTABLE
_COREPACK_EXECUTABLE = "corepack"
_UV_SYNC_ARGUMENTS = ("sync", "--frozen")
_PNPM_INSTALL_ARGUMENTS = ("pnpm", "install", "--frozen-lockfile")
_PNPM_BUILD_ARGUMENTS = ("pnpm", "build")
_COREPACK_PROMPT_VARIABLE = "COREPACK_ENABLE_DOWNLOAD_PROMPT"
_COREPACK_PROMPT_OFF = "0"
_INHERITED_BUILD_VARIABLES = frozenset({"VIRTUAL_ENV", "PYTHONPATH"})
_ENVIRONMENT_BUILD_TIMEOUT_SECONDS = 1800
_VOICE_BRIDGE_BUILD_TIMEOUT_SECONDS = 900
_OUTPUT_TAIL_CHARS = 2000
_PREPARED_EVENT = "release_prepared"
_REUSED_EVENT = "release_reused"
_DISCARDED_EVENT = "release_discarded"
_NO_SOURCE = "the installation keeps no repository yet and no source was named to clone"
_COMMIT_UNKNOWN = "revision {revision} names no commit of the kept repository: {error}"
_REVISION_NOT_FULL = "revision {revision} resolves to {resolved}; releases are named by the full commit"
_TOOL_MISSING = "{tool} was not found; the machine's prerequisites must provide it before a release can be built"
_STEP_FAILED = "{command} exited {status}: {output}"
_BUILD_OUTPUT_MISSING = "the voice bridge build produced no {path}"
_GIT_FAILED = "git {operation} failed: {error}"
_OPERATION_CLONE = "clone"
_OPERATION_FETCH = "fetch"
_OPERATION_WORKTREE_ADD = "worktree add"


class PreparationStep(StrEnum):
    """The steps of preparing a release, named by the failure that ended one."""

    REPOSITORY = "repository"
    FETCH = "fetch"
    WORKTREE = "worktree"
    ENVIRONMENT = "environment"
    VOICE_BRIDGE = "voice_bridge"


class ReleasePreparationError(RuntimeError):
    """A release could not be prepared; nothing live changed and no partial release remains."""

    def __init__(self, step: PreparationStep, detail: str) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail


@dataclass(frozen=True)
class PreparedRelease:
    """A release ready to run: its revision, its folder, and whether it was already built."""

    revision: str
    path: Path
    reused: bool


def keep_repository(layout: InstallationLayout, source: str | None = None) -> Repo:
    """The installation's kept repository, cloned from ``source`` once when it does not exist yet."""
    if layout.repository.is_dir():
        return Repo(str(layout.repository))
    if source is None:
        raise ReleasePreparationError(PreparationStep.REPOSITORY, _NO_SOURCE)
    layout.root.mkdir(parents=True, exist_ok=True)
    try:
        repository = Repo.clone_from(source, str(layout.repository), bare=True)
        repository.git.config(_FETCH_CONFIG_KEY, _FETCH_REFSPEC)
    except GitCommandError as error:
        shutil.rmtree(layout.repository, ignore_errors=True)
        raise ReleasePreparationError(
            PreparationStep.REPOSITORY, _GIT_FAILED.format(operation=_OPERATION_CLONE, error=error)
        ) from error
    return repository


def source_of(layout: InstallationLayout) -> str:
    """The repository the installation follows: the remote of its kept repository."""
    return str(Repo(str(layout.repository)).remote(_REMOTE_NAME).url)


def fetch_source(layout: InstallationLayout) -> None:
    """Bring the kept repository up to date with its source, tags included."""
    try:
        Repo(str(layout.repository)).git.fetch(*_FETCH_ARGUMENTS)
    except GitCommandError as error:
        raise ReleasePreparationError(
            PreparationStep.FETCH, _GIT_FAILED.format(operation=_OPERATION_FETCH, error=error)
        ) from error


def resolve_commit(layout: InstallationLayout, reference: str) -> str:
    """The full commit a reference names in the kept repository."""
    try:
        return Repo(str(layout.repository)).commit(reference).hexsha
    except (GitCommandError, BadName, ValueError) as error:
        raise ReleasePreparationError(
            PreparationStep.WORKTREE, _COMMIT_UNKNOWN.format(revision=reference, error=error)
        ) from error


def prepare_release(layout: InstallationLayout, revision: str) -> PreparedRelease:
    """Add the release at ``revision`` and build it in place; reuse it when it is already built.

    A folder that is not a complete build is discarded and prepared again. A failure discards what this
    attempt created and raises with the step that failed.
    """
    resolved = resolve_commit(layout, revision)
    if resolved != revision:
        raise ReleasePreparationError(
            PreparationStep.WORKTREE, _REVISION_NOT_FULL.format(revision=revision, resolved=resolved)
        )
    path = layout.release_path(revision)
    if path.exists():
        if _is_built(path):
            logger.info(_REUSED_EVENT, revision=revision)
            return PreparedRelease(revision=revision, path=path, reused=True)
        remove_release(layout, revision)
    repository = Repo(str(layout.repository))
    try:
        layout.releases.mkdir(parents=True, exist_ok=True)
        repository.git.worktree("add", "--detach", str(path), revision)
        _build_environment(path)
        _build_voice_bridge(path)
        (path / _VENV_DIRECTORY / _BUILT_MARKER).touch()
    except (GitCommandError, OSError) as error:
        remove_release(layout, revision)
        raise ReleasePreparationError(
            PreparationStep.WORKTREE, _GIT_FAILED.format(operation=_OPERATION_WORKTREE_ADD, error=error)
        ) from error
    except ReleasePreparationError:
        remove_release(layout, revision)
        raise
    logger.info(_PREPARED_EVENT, revision=revision)
    return PreparedRelease(revision=revision, path=path, reused=False)


def remove_release(layout: InstallationLayout, revision: str) -> None:
    """Remove a release folder and its worktree registration; nothing live names it."""
    path = layout.release_path(revision)
    repository = Repo(str(layout.repository))
    try:
        repository.git.worktree("remove", "--force", str(path))
    except GitCommandError:
        shutil.rmtree(path, ignore_errors=True)
    repository.git.worktree("prune")
    logger.info(_DISCARDED_EVENT, revision=revision)


def _is_built(path: Path) -> bool:
    """Whether a release folder holds a complete build."""
    return (path / _VENV_DIRECTORY / _BUILT_MARKER).is_file()


def _build_environment(path: Path) -> None:
    """Build the release's locked Python environment in place."""
    uv = shutil.which(_UV_EXECUTABLE) or str(Path.home() / _UV_FALLBACK)
    if not Path(uv).is_file():
        raise ReleasePreparationError(PreparationStep.ENVIRONMENT, _TOOL_MISSING.format(tool=_UV_EXECUTABLE))
    _run(PreparationStep.ENVIRONMENT, [uv, *_UV_SYNC_ARGUMENTS], path, _ENVIRONMENT_BUILD_TIMEOUT_SECONDS)


def _build_voice_bridge(path: Path) -> None:
    """Install and build the Discord voice bridge when the release carries it."""
    bridge = path / _VOICE_BRIDGE_PATH
    if not bridge.is_dir():
        return
    corepack = shutil.which(_COREPACK_EXECUTABLE)
    if corepack is None:
        raise ReleasePreparationError(PreparationStep.VOICE_BRIDGE, _TOOL_MISSING.format(tool=_COREPACK_EXECUTABLE))
    for arguments in (_PNPM_INSTALL_ARGUMENTS, _PNPM_BUILD_ARGUMENTS):
        _run(PreparationStep.VOICE_BRIDGE, [corepack, *arguments], bridge, _VOICE_BRIDGE_BUILD_TIMEOUT_SECONDS)
    if not (bridge / _VOICE_BRIDGE_OUTPUT).is_dir():
        raise ReleasePreparationError(
            PreparationStep.VOICE_BRIDGE, _BUILD_OUTPUT_MISSING.format(path=bridge / _VOICE_BRIDGE_OUTPUT)
        )


def release_process_environment() -> dict[str, str]:
    """The caller's environment without the interpreter selectors a release's own processes must not inherit."""
    inherited = {
        # guard: direct-env-read - allowed: child-process environment construction
        key: value for key, value in os.environ.items() if key not in _INHERITED_BUILD_VARIABLES
    }  # fmt: skip
    inherited[_COREPACK_PROMPT_VARIABLE] = _COREPACK_PROMPT_OFF
    return inherited


def _run(step: PreparationStep, command: list[str], cwd: Path, timeout_seconds: int) -> None:
    """Run one build command to completion, raising with the tail of its output when it fails."""
    # subprocess is the point: uv and corepack have no Python API, and a release must build with
    # its own toolchain outside this interpreter.
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=release_process_environment(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleasePreparationError(step, _STEP_FAILED.format(command=command[0], status=-1, output=error)) from error
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout)[-_OUTPUT_TAIL_CHARS:]
        raise ReleasePreparationError(
            step, _STEP_FAILED.format(command=" ".join(command), status=completed.returncode, output=output)
        )

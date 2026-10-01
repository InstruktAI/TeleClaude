"""Manage Antigravity's exact workspace trust entries for todo worktrees."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.paths import STATE_DIR
from teleclaude.slug import validate_slug

logger = get_logger(__name__)

_GEMINI_CONFIG_DIRECTORY = ".gemini"
_ANTIGRAVITY_CONFIG_DIRECTORY = "antigravity-cli"
_SETTINGS_FILENAME = "settings.json"
_TRUSTED_WORKSPACES_KEY: Final = "trustedWorkspaces"
_WORKTREE_TRUST_LOCK_NAME = "agy-worktree-trust"
_TRUST_STORE_UPDATE_FAILED_EVENT = "agy_workspace_trust_update_failed"
_INVALID_TRUST_STORE_REASON = "unsupported settings shape"
_LEGACY_TRASH_DIRECTORY = ".trash"


class _InvalidTrustStore(Exception):
    """The vendor settings do not have the supported object shape."""


class _TrustSettings(TypedDict, total=False):
    trustedWorkspaces: object


def _settings_path() -> Path:
    return Path.home() / _GEMINI_CONFIG_DIRECTORY / _ANTIGRAVITY_CONFIG_DIRECTORY / _SETTINGS_FILENAME


def _update_trust_store(mutate: Callable[[list[str]], bool]) -> None:
    settings_path = _settings_path()
    try:
        try:
            settings_path.stat()
        except FileNotFoundError:
            return

        settings_file = FileTransaction(settings_path.resolve())
        with file_transaction(STATE_DIR / _WORKTREE_TRUST_LOCK_NAME):
            raw_settings = settings_file.read_text()
            parsed_settings: object = json.loads(raw_settings)
            if not isinstance(parsed_settings, dict):
                raise _InvalidTrustStore(_INVALID_TRUST_STORE_REASON)

            settings = cast(_TrustSettings, parsed_settings)
            if _TRUSTED_WORKSPACES_KEY not in settings:
                return
            workspace_value = settings[_TRUSTED_WORKSPACES_KEY]
            if not isinstance(workspace_value, list) or any(
                not isinstance(workspace, str) for workspace in workspace_value
            ):
                raise _InvalidTrustStore(_INVALID_TRUST_STORE_REASON)

            workspaces = cast(list[str], workspace_value)
            if mutate(workspaces):
                settings_file.replace_text(json.dumps(settings, indent=2))
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError, _InvalidTrustStore) as exc:
        logger.warning(_TRUST_STORE_UPDATE_FAILED_EVENT, reason=str(exc))


def add_worktree_trust(project_root: Path, worktree_root: Path) -> None:
    """Trust a worktree only when Antigravity already trusts its main checkout."""

    def add_if_project_is_trusted(workspaces: list[str]) -> bool:
        resolved_project_root = project_root.resolve()
        resolved_worktree_root = worktree_root.resolve()
        if str(resolved_project_root) not in workspaces or str(resolved_worktree_root) in workspaces:
            return False
        workspaces.append(str(resolved_worktree_root))
        return True

    _update_trust_store(add_if_project_is_trusted)


def remove_worktree_trust(worktree_root: Path) -> None:
    """Remove the released worktree's exact resolved path from Antigravity's list."""

    def remove_released_worktree(workspaces: list[str]) -> bool:
        resolved_worktree_root = str(worktree_root.resolve())
        retained_workspaces = [workspace for workspace in workspaces if workspace != resolved_worktree_root]
        if len(retained_workspaces) == len(workspaces):
            return False
        workspaces[:] = retained_workspaces
        return True

    _update_trust_store(remove_released_worktree)


def move_worktree_trust(project_root: Path, old_worktree_root: Path, new_worktree_root: Path) -> None:
    """Move trust with a renamed worktree, preserving the main-checkout precondition."""

    def move_renamed_worktree(workspaces: list[str]) -> bool:
        resolved_project_root = str(project_root.resolve())
        resolved_old_worktree_root = str(old_worktree_root.resolve())
        resolved_new_worktree_root = str(new_worktree_root.resolve())
        retained_workspaces = [workspace for workspace in workspaces if workspace != resolved_old_worktree_root]
        changed = len(retained_workspaces) != len(workspaces)
        if resolved_project_root in retained_workspaces and resolved_new_worktree_root not in retained_workspaces:
            retained_workspaces.append(resolved_new_worktree_root)
            changed = True
        if changed:
            workspaces[:] = retained_workspaces
        return changed

    _update_trust_store(move_renamed_worktree)


def _is_vanished_worktree(workspace: str, project_root: Path) -> bool:
    workspace_path = Path(workspace)
    if not workspace_path.is_absolute():
        return False

    resolved_project_root = project_root.resolve()
    worktrees_root = (resolved_project_root / WORKTREE_DIR).resolve()
    resolved_workspace_path = workspace_path.resolve()
    is_slug_worktree = resolved_workspace_path.parent == worktrees_root
    is_legacy_trash_child = (
        worktrees_root / _LEGACY_TRASH_DIRECTORY
    ).resolve().parent == worktrees_root and resolved_workspace_path.parent == (
        worktrees_root / _LEGACY_TRASH_DIRECTORY
    ).resolve()
    if not is_slug_worktree and not is_legacy_trash_child:
        return False

    if is_slug_worktree:
        try:
            validate_slug(resolved_workspace_path.name)
        except ValueError:
            return False

    try:
        workspace_path.stat()
    except FileNotFoundError:
        return True
    return False


def remove_vanished_worktree_trust(project_root: Path) -> None:
    """Remove only absent slug-worktree and retired-trash entries for this project."""

    def remove_vanished_worktrees(workspaces: list[str]) -> bool:
        resolved_project_root = project_root.resolve()
        retained_workspaces = [
            workspace for workspace in workspaces if not _is_vanished_worktree(workspace, resolved_project_root)
        ]
        if len(retained_workspaces) == len(workspaces):
            return False
        workspaces[:] = retained_workspaces
        return True

    _update_trust_store(remove_vanished_worktrees)

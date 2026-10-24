"""Eagerly reconcile the installed project's retained development checkout."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.config.checkout_association import CheckoutPurpose, checkout_association_for
from teleclaude.core.checkout_transition import source_transition_blockers
from teleclaude.core.integration.development_maintenance import run_development_maintenance
from teleclaude.core.next_machine.worktree_environment import rebind_retained_worktree_environments
from teleclaude.core.next_machine.worktree_home import ensure_development_worktree_home
from teleclaude.core.next_machine.worktrees import ensure_development_dependencies
from teleclaude.deployment.release_checkout import installed_checkout_root
from teleclaude.entrypoints.environment_defaults import ensure_environment_defaults
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import PROJECTS_MANIFEST_PATH, STATE_DIR
from teleclaude.project_setup.init_flow import (
    associate_development_checkout,
    project_identity,
    register_installed_project,
)

logger = get_logger(__name__)

_RECEIPT_PATH = STATE_DIR / "development-checkout.json"
_RECEIPT_LOCK = STATE_DIR / "development-checkout.lock"
_SCHEMA_VERSION: Literal[1] = 1
_RECEIPT_VERSION_FIELD = "schema_version"
_RECEIPT_TEMP_SUFFIX = ".tmp"
_ENCODING = "utf-8"
_ORIGIN_REMOTE = "origin"
_MAIN_BRANCH = "main"
_GIT_CLEAN = "the owned staging clone is not complete"
_GIT_DIRECTORY = ".git"
_TELECLAUDE_DIRECTORY = ".teleclaude"
_WORKFLOW_DATABASES = (
    "todos.db",
    "todos.db-wal",
    "todos.db-shm",
    "todos.github.db",
    "todos.github.db-wal",
    "todos.github.db-shm",
)
_LOCK_APPEND_MODE = "a"
_CLONE_OPTIONS = ("--no-hardlinks", "--single-branch", "--branch", _MAIN_BRANCH)
_DEVELOPMENT_CLONE_READY = "development_checkout_clone_ready"
_DEVELOPMENT_CHECKOUT_READY = "development_checkout_ready"
_DEVELOPMENT_CHECKOUT_FAILED = "development_checkout_failed"
_BLOCKER_SEPARATOR = "; "
_BLOCKER_DETAIL = "{kind} {subject}: {recovery}"
_INVALID_RECEIPT = "the development-checkout receipt is unreadable or has an unsupported shape"
_RECEIPT_OWNER_MISMATCH = "the retained development-checkout receipt belongs to another installation"
_SOURCE_IDENTITY_CHANGED = "the installed project's identity or origin changed during provisioning"
_DESTINATION_CONFLICT = "the development-checkout destination conflicts with the recorded project identity"
_STAGING_CONFLICT = "the owned development staging path is occupied by unrelated or incomplete state"
_WORKFLOW_STORE_CONFLICT = "the existing development checkout already contains its own workflow store"
_ORIGIN_CREDENTIAL_REFUSAL = (
    "origin contains embedded credentials; remove them before provisioning the development checkout"
)


class DevelopmentCheckoutStep(StrEnum):
    """Closed identities for durable development-checkout provisioning steps."""

    PREFLIGHT = "preflight"
    PRIMARY_REGISTRATION = "primary_registration"
    CLONE = "clone"
    TRANSITION = "transition"
    ASSOCIATION = "association"
    DEVELOPMENT_HOME = "development_home"
    ENVIRONMENT_SETTINGS = "environment_settings"
    DEPENDENCY_PREPARATION = "dependency_preparation"
    RETAINED_WORKTREE_ENVIRONMENT_REBIND = "retained_worktree_environment_rebind"
    INITIAL_DEVELOPMENT_MAINTENANCE = "initial_development_maintenance"


class _DevelopmentCheckoutReceipt(BaseModel):
    """Atomic progress record that owns the destination and staging checkout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
    installed_root: str
    destination: str
    staging_path: str
    project_identity: str
    origin_digest: str
    completed_steps: tuple[DevelopmentCheckoutStep, ...] = ()
    in_progress_step: DevelopmentCheckoutStep | None = None
    failed_step: DevelopmentCheckoutStep | None = None


@dataclass(frozen=True)
class DevelopmentCheckoutResult:
    """Terminal readiness facts for one reconciliation request."""

    ready: bool
    installed_root: Path | None = None
    development_root: Path | None = None
    step: DevelopmentCheckoutStep | None = None
    error: str | None = None


class DevelopmentCheckoutError(RuntimeError):
    """A provisioning step stopped before the development checkout was ready."""

    def __init__(self, step: DevelopmentCheckoutStep, detail: str) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"{step}: {detail}")


@contextmanager
def _receipt_lock() -> Iterator[None]:
    _RECEIPT_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with _RECEIPT_LOCK.open(_LOCK_APPEND_MODE, encoding=_ENCODING) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _origin_urls(project_root: Path) -> tuple[str, ...]:
    repository = Repo(str(project_root), search_parent_directories=False)
    return tuple(repository.remote(_ORIGIN_REMOTE).urls)


def _origin_digest(urls: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(urls).encode(_ENCODING)).hexdigest()


def _validate_receipt_owner(receipt: _DevelopmentCheckoutReceipt, installed_root: Path) -> None:
    expected_destination = installed_root.with_name(f"{installed_root.name}-dev")
    destination = Path(receipt.destination)
    staging = Path(receipt.staging_path)
    staging_prefix = f".{installed_root.name}-dev.staging."
    if (
        Path(receipt.installed_root) != installed_root
        or destination != expected_destination
        or staging.parent != installed_root.parent
        or not staging.name.startswith(staging_prefix)
    ):
        raise ValueError(_RECEIPT_OWNER_MISMATCH)


def _reject_embedded_origin_credentials(urls: tuple[str, ...]) -> None:
    for url in urls:
        parsed = urlsplit(url)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(_ORIGIN_CREDENTIAL_REFUSAL)


def _new_receipt(installed_root: Path) -> _DevelopmentCheckoutReceipt:
    urls = _origin_urls(installed_root)
    if not urls:
        raise ValueError("the installed checkout has no origin remote")
    _reject_embedded_origin_credentials(urls)
    destination = installed_root.with_name(f"{installed_root.name}-dev")
    staging = installed_root.with_name(f".{installed_root.name}-dev.staging.{uuid4().hex}")
    while staging.exists() or staging.is_symlink():
        staging = installed_root.with_name(f".{installed_root.name}-dev.staging.{uuid4().hex}")
    return _DevelopmentCheckoutReceipt(
        installed_root=str(installed_root),
        destination=str(destination),
        staging_path=str(staging),
        project_identity=project_identity(installed_root),
        origin_digest=_origin_digest(urls),
    )


def _read_receipt() -> _DevelopmentCheckoutReceipt | None:
    if not _RECEIPT_PATH.exists():
        return None
    try:
        payload = json.loads(_RECEIPT_PATH.read_text(encoding=_ENCODING))
        if not isinstance(payload, dict) or payload.get(_RECEIPT_VERSION_FIELD) != _SCHEMA_VERSION:
            raise ValueError(_INVALID_RECEIPT)
        return _DevelopmentCheckoutReceipt.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(_INVALID_RECEIPT) from exc


def _write_receipt(receipt: _DevelopmentCheckoutReceipt) -> None:
    _RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _RECEIPT_PATH.with_name(f"{_RECEIPT_PATH.name}.{uuid4().hex}{_RECEIPT_TEMP_SUFFIX}")
    try:
        temporary.write_text(receipt.model_dump_json(), encoding=_ENCODING)
        os.replace(temporary, _RECEIPT_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def _update_receipt(receipt: _DevelopmentCheckoutReceipt, **changes: object) -> _DevelopmentCheckoutReceipt:
    updated = receipt.model_copy(update=changes)
    _write_receipt(updated)
    return updated


def _run_step[RESULT](
    receipt: _DevelopmentCheckoutReceipt,
    step: DevelopmentCheckoutStep,
    operation: Callable[[], RESULT],
) -> tuple[_DevelopmentCheckoutReceipt, RESULT]:
    """Persist step ownership before acting and completion only after it succeeds."""
    receipt = _update_receipt(receipt, in_progress_step=step, failed_step=None)
    try:
        result = operation()
    except Exception as exc:
        receipt = _update_receipt(receipt, failed_step=step)
        raise DevelopmentCheckoutError(step, _receipt_error_detail(exc, Path(receipt.installed_root))) from exc
    completed = tuple(dict.fromkeys((*receipt.completed_steps, step)))
    receipt = _update_receipt(receipt, completed_steps=completed, in_progress_step=None, failed_step=None)
    return receipt, result


def _receipt_error_detail(exc: Exception, installed_root: Path) -> str:
    detail = str(exc) or type(exc).__name__
    try:
        urls = _origin_urls(installed_root)
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError):
        urls = ()
    for url in urls:
        detail = detail.replace(url, "<origin>")
    return detail


def _workflow_store_exists(root: Path) -> bool:
    state = root / _TELECLAUDE_DIRECTORY
    return any((state / name).exists() or (state / name).is_symlink() for name in _WORKFLOW_DATABASES)


def _validate_companion(
    path: Path,
    receipt: _DevelopmentCheckoutReceipt,
    *,
    associated: bool,
) -> None:
    if path.resolve() not in {Path(receipt.destination).resolve(), Path(receipt.staging_path).resolve()}:
        raise ValueError(_DESTINATION_CONFLICT)
    if (
        path.is_symlink()
        or not path.is_dir()
        or (path / _GIT_DIRECTORY).is_symlink()
        or not (path / _GIT_DIRECTORY).is_dir()
    ):
        raise ValueError(_DESTINATION_CONFLICT)
    if associated:
        association = checkout_association_for(Path(receipt.installed_root), PROJECTS_MANIFEST_PATH)
        if (
            association is None
            or association.purpose is not CheckoutPurpose.INSTALLED
            or association.development_checkout != Path(receipt.destination)
        ):
            raise ValueError(_DESTINATION_CONFLICT)
    try:
        if project_identity(path) != receipt.project_identity:
            raise ValueError(_DESTINATION_CONFLICT)
        urls = _origin_urls(path)
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError) as exc:
        raise ValueError(_DESTINATION_CONFLICT) from exc
    if not urls or _origin_digest(urls) != receipt.origin_digest:
        raise ValueError(_DESTINATION_CONFLICT)
    if _workflow_store_exists(path):
        raise ValueError(_WORKFLOW_STORE_CONFLICT)


def _validate_staging_clone(path: Path, receipt: _DevelopmentCheckoutReceipt) -> None:
    _validate_companion(path, receipt, associated=False)
    try:
        repository = Repo(str(path), search_parent_directories=False)
        complete = (
            not repository.head.is_detached
            and repository.active_branch.name == _MAIN_BRANCH
            and not repository.is_dirty(untracked_files=True)
        )
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError) as exc:
        raise ValueError(_GIT_CLEAN) from exc
    if not complete:
        raise ValueError(_GIT_CLEAN)


def _clone_or_reuse(
    receipt: _DevelopmentCheckoutReceipt,
    *,
    allow_existing_destination: bool,
    allow_staging_resume: bool,
) -> Path:
    installed = Path(receipt.installed_root)
    destination = Path(receipt.destination)
    staging = Path(receipt.staging_path)
    association = checkout_association_for(installed, PROJECTS_MANIFEST_PATH)
    if association is not None and (
        association.purpose is not CheckoutPurpose.INSTALLED or association.development_checkout != destination
    ):
        raise ValueError(_DESTINATION_CONFLICT)
    if destination.exists() or destination.is_symlink():
        if not allow_existing_destination and association is None:
            raise ValueError(_DESTINATION_CONFLICT)
        _validate_companion(destination, receipt, associated=association is not None)
        return destination

    if staging.exists() or staging.is_symlink():
        if staging.is_symlink() or not staging.is_dir():
            raise ValueError(_STAGING_CONFLICT)
        if not allow_staging_resume:
            raise ValueError(_STAGING_CONFLICT)
        try:
            _validate_staging_clone(staging, receipt)
        except ValueError as exc:
            if (
                receipt.in_progress_step is not DevelopmentCheckoutStep.CLONE
                or DevelopmentCheckoutStep.CLONE in receipt.completed_steps
                or _workflow_store_exists(staging)
            ):
                raise ValueError(_STAGING_CONFLICT) from exc
            shutil.rmtree(staging)

    if not staging.exists():
        urls = _origin_urls(installed)
        _reject_embedded_origin_credentials(urls)
        repository = Repo.clone_from(
            urls[0],
            str(staging),
            multi_options=list(_CLONE_OPTIONS),
        )
        for url in urls[1:]:
            repository.git.remote("set-url", "--add", _ORIGIN_REMOTE, url)
        _validate_staging_clone(staging, receipt)

    try:
        staging.rename(destination)
    except OSError as exc:
        raise ValueError(_DESTINATION_CONFLICT) from exc
    _validate_companion(destination, receipt, associated=False)
    logger.info(_DEVELOPMENT_CLONE_READY, installed_root=str(installed), development_root=str(destination))
    return destination


def _check_source_transition(installed_root: Path) -> None:
    blockers = source_transition_blockers(installed_root)
    if blockers:
        detail = _BLOCKER_SEPARATOR.join(
            _BLOCKER_DETAIL.format(kind=item.kind, subject=item.subject, recovery=item.recovery) for item in blockers
        )
        raise ValueError(detail)


def _run_reconciliation(
    installed_root: Path,
    receipt: _DevelopmentCheckoutReceipt,
    *,
    allow_existing_destination: bool,
    allow_staging_resume: bool,
) -> _DevelopmentCheckoutReceipt:
    destination = Path(receipt.destination)
    current_identity = project_identity(installed_root)
    current_origins = _origin_urls(installed_root)
    if current_identity != receipt.project_identity or _origin_digest(current_origins) != receipt.origin_digest:
        raise ValueError(_SOURCE_IDENTITY_CHANGED)

    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.PRIMARY_REGISTRATION,
        lambda: register_installed_project(installed_root),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.CLONE,
        lambda: _clone_or_reuse(
            receipt,
            allow_existing_destination=allow_existing_destination,
            allow_staging_resume=allow_staging_resume,
        ),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.TRANSITION,
        lambda: _check_source_transition(installed_root),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.ASSOCIATION,
        lambda: associate_development_checkout(installed_root, destination),
    )

    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.DEVELOPMENT_HOME,
        lambda: ensure_development_worktree_home(destination),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.ENVIRONMENT_SETTINGS,
        lambda: ensure_environment_defaults(destination),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.DEPENDENCY_PREPARATION,
        lambda: ensure_development_dependencies(destination),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.RETAINED_WORKTREE_ENVIRONMENT_REBIND,
        lambda: rebind_retained_worktree_environments(installed_root),
    )
    receipt, _ = _run_step(
        receipt,
        DevelopmentCheckoutStep.INITIAL_DEVELOPMENT_MAINTENANCE,
        lambda: run_development_maintenance(destination, None),
    )
    return receipt


def converge_development_checkout() -> DevelopmentCheckoutResult:
    """Converge the installed project's registered sibling development checkout."""
    installed_root = installed_checkout_root()
    if installed_root is None:
        return DevelopmentCheckoutResult(ready=True)
    installed_root = installed_root.expanduser().resolve()
    try:
        with _receipt_lock():
            receipt = _read_receipt()
            receipt_preexisted = receipt is not None
            initial_association = checkout_association_for(installed_root, PROJECTS_MANIFEST_PATH)
            if receipt is None:
                receipt = _new_receipt(installed_root)
                _write_receipt(receipt)
            else:
                _validate_receipt_owner(receipt, installed_root)
            receipt = _run_reconciliation(
                installed_root,
                receipt,
                allow_existing_destination=receipt_preexisted or initial_association is not None,
                allow_staging_resume=receipt_preexisted,
            )
        logger.info(
            _DEVELOPMENT_CHECKOUT_READY,
            installed_root=str(installed_root),
            development_root=receipt.destination,
            purpose=CheckoutPurpose.DEVELOPMENT,
        )
        return DevelopmentCheckoutResult(True, installed_root, Path(receipt.destination))
    except DevelopmentCheckoutError as exc:
        logger.error(
            _DEVELOPMENT_CHECKOUT_FAILED,
            installed_root=str(installed_root),
            development_root=str(installed_root.with_name(f"{installed_root.name}-dev")),
            step=exc.step,
            error=exc.detail,
        )
        return DevelopmentCheckoutResult(
            False,
            installed_root,
            installed_root.with_name(f"{installed_root.name}-dev"),
            exc.step,
            exc.detail,
        )
    except Exception as exc:
        logger.exception(_DEVELOPMENT_CHECKOUT_FAILED, installed_root=str(installed_root), error=str(exc))
        return DevelopmentCheckoutResult(
            False,
            installed_root,
            installed_root.with_name(f"{installed_root.name}-dev"),
            DevelopmentCheckoutStep.PREFLIGHT,
            _receipt_error_detail(exc, installed_root),
        )

"""Purpose-bound maintenance selection and execution for development checkouts."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

from teleclaude.checkpoint_model import load_checkpoint_model, load_committed_checkpoint_model
from teleclaude.config.checkout_association import CheckoutPurpose, checkout_association_for
from teleclaude.constants import CheckpointActivation, CheckpointActivationBinding, CheckpointModel, MaintenanceAction
from teleclaude.deployment.release_checkout import is_installed_checkout, is_release_installation, selected_revision
from teleclaude.git import Repo
from teleclaude.paths import PROJECTS_MANIFEST_PATH, TELECLAUDE_SOURCE_HOME

DEVELOPMENT_MAINTENANCE_ACTION_ID = "development-maintenance"
DEVELOPMENT_MAINTENANCE_MODULE = "teleclaude.core.integration.development_maintenance"
POST_COMMIT_MAINTENANCE_MODULE = "teleclaude.core.integration.post_commit_maintenance"
DEVELOPMENT_MAINTENANCE_ROOT_OPTION = "--root"
DEVELOPMENT_MAINTENANCE_AFTER_SHA_OPTION = "--after-sha"
DEVELOPMENT_MAINTENANCE_BEFORE_SHA_OPTION = "--before-sha"
DEVELOPMENT_SAFE_PATH_FLAG = "-P"
DEVELOPMENT_MODULE_EXECUTION_FLAG = "-m"
DEVELOPMENT_PYTHON = Path(".venv/bin/python")
NEUTRAL_CWD = Path.home()
_MAIN_BRANCH_NAME = "main"
_INTERPRETER_PLACEHOLDER = "{interpreter}"
_AFTER_SHA_PLACEHOLDER = "{after_sha}"
_BEFORE_SHA_PLACEHOLDER = "{before_sha}"
_DEVELOPMENT_EXECUTOR_REFUSAL = "development executor requires a registered development checkout"
_PYTHONPATH_ENVIRONMENT_VARIABLE = "PYTHONPATH"


def is_development_checkout(root: Path) -> bool:
    """Whether the registry records this checkout as the logical project's development location."""
    association = checkout_association_for(root.resolve(), TELECLAUDE_SOURCE_HOME / PROJECTS_MANIFEST_PATH.name)
    return association is not None and association.purpose is CheckoutPurpose.DEVELOPMENT


def development_maintenance_model(root: Path) -> CheckpointModel:
    """Return the single supported development activation; source-defined project actions are excluded."""
    resolved_root = root.resolve()
    action = MaintenanceAction(
        id=DEVELOPMENT_MAINTENANCE_ACTION_ID,
        command=(
            _INTERPRETER_PLACEHOLDER,
            DEVELOPMENT_SAFE_PATH_FLAG,
            DEVELOPMENT_MODULE_EXECUTION_FLAG,
            DEVELOPMENT_MAINTENANCE_MODULE,
            DEVELOPMENT_MAINTENANCE_ROOT_OPTION,
            str(resolved_root),
            DEVELOPMENT_MAINTENANCE_AFTER_SHA_OPTION,
            _AFTER_SHA_PLACEHOLDER,
            DEVELOPMENT_MAINTENANCE_BEFORE_SHA_OPTION,
            _BEFORE_SHA_PLACEHOLDER,
        ),
        main_only=True,
        precedence=10,
        runs_while_serving=True,
    )
    return CheckpointModel(
        actions={},
        maintenance={action.id: action},
        bindings=(),
        activation_bindings=(CheckpointActivationBinding(CheckpointActivation.CANONICAL_MAIN, (action.id,)),),
    )


def development_executor(root: Path) -> tuple[str, Path]:
    """Return installed Python and neutral cwd for an explicitly targeted development operation."""
    association = checkout_association_for(root.resolve(), TELECLAUDE_SOURCE_HOME / PROJECTS_MANIFEST_PATH.name)
    if association is None or association.purpose is not CheckoutPurpose.DEVELOPMENT:
        raise ValueError(_DEVELOPMENT_EXECUTOR_REFUSAL)
    return str(association.project_root / DEVELOPMENT_PYTHON), NEUTRAL_CWD


def maintenance_executor(root: Path) -> tuple[str, Path]:
    """Select installed safe-path execution for development, otherwise preserve local behavior."""
    if is_development_checkout(root):
        return development_executor(root)
    return sys.executable, root


def development_drain_execution(root: Path) -> tuple[list[str], Path]:
    """Build the installed-controller command that drains a development checkout's queue."""
    resolved_root = root.resolve()
    interpreter, cwd = development_executor(resolved_root)
    return (
        [
            interpreter,
            DEVELOPMENT_SAFE_PATH_FLAG,
            DEVELOPMENT_MODULE_EXECUTION_FLAG,
            POST_COMMIT_MAINTENANCE_MODULE,
            DEVELOPMENT_MAINTENANCE_ROOT_OPTION,
            str(resolved_root),
        ],
        cwd,
    )


def maintenance_model(root: Path) -> CheckpointModel:
    """Load normal committed maintenance or the fixed development-only action set."""
    resolved_root = root.resolve()
    if is_development_checkout(resolved_root):
        return development_maintenance_model(resolved_root)
    revision = selected_revision(resolved_root)
    if revision is None:
        return load_checkpoint_model(str(resolved_root))
    return load_committed_checkpoint_model(resolved_root, revision)


def on_demand_maintenance_model(root: Path, revision: str) -> CheckpointModel:
    """Load the committed on-demand action set unless the target is development."""
    resolved_root = root.resolve()
    if is_development_checkout(resolved_root):
        return development_maintenance_model(resolved_root)
    return load_committed_checkpoint_model(resolved_root, revision)


def maintenance_interpreter(root: Path) -> str:
    """Return the interpreter used by the selected maintenance executor."""
    return maintenance_executor(root)[0]


def maintenance_cwd(root: Path) -> Path:
    """Return the working directory used by the selected maintenance executor."""
    return maintenance_executor(root)[1]


def maintenance_environment(root: Path, environment: Mapping[str, str]) -> dict[str, str]:
    """Bind safe-path development controllers to the installed source package."""
    selected = dict(environment)
    association = checkout_association_for(root.resolve(), TELECLAUDE_SOURCE_HOME / PROJECTS_MANIFEST_PATH.name)
    if association is not None and association.purpose is CheckoutPurpose.DEVELOPMENT:
        selected[_PYTHONPATH_ENVIRONMENT_VARIABLE] = str(association.project_root)
    return selected


def eligible_maintenance_posture(root: Path, repository: Repo) -> bool:
    """Admit release installations or a canonical main checkout, reading registered purpose first."""
    association = checkout_association_for(root.resolve(), TELECLAUDE_SOURCE_HOME / PROJECTS_MANIFEST_PATH.name)
    if association is not None and association.purpose is CheckoutPurpose.DEVELOPMENT:
        return not repository.head.is_detached and repository.active_branch.name == _MAIN_BRANCH_NAME
    if association is not None and association.purpose is CheckoutPurpose.INSTALLED and is_installed_checkout(root):
        return is_release_installation(root) or (
            not repository.head.is_detached and repository.active_branch.name == _MAIN_BRANCH_NAME
        )
    return is_release_installation(root) or (
        not repository.head.is_detached and repository.active_branch.name == _MAIN_BRANCH_NAME
    )

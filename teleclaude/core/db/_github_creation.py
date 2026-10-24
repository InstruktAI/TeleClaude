"""Prepare and validate one workflow binding inside the existing session-creation transaction."""

from __future__ import annotations

from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from teleclaude.config.loader import github_actor_for_role
from teleclaude.config.machine import config
from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.core import db_models
from teleclaude.core.models import Session
from teleclaude.core.operation_caller_identity import get_relayed_caller
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.core.roles import Role, resolve_session_role
from teleclaude.core.workflow_store.selection import selected_workflow_store_backend
from teleclaude.types.github_binding import GitHubSessionBinding, GitHubWorkTarget
from teleclaude.types.session_creation import WorkflowChildCreation, WorkflowDriverCreation

_INVALID_CREATION = "Workflow startup binding is incomplete or disagrees with the resolved session"
_PARENT_UNAVAILABLE = "Admitted workflow parent is missing, foreign or unavailable"
_PARENT_MISMATCH = "Admitted workflow parent binding disagrees with the item or child actor"


def validate_workflow_creation_address(
    creation: WorkflowDriverCreation | None,
    computer: str,
    initiator_id: str | None = None,
    initiator_computer: str | None = None,
) -> None:
    """Qualify only carrier-bearing creation before any existing parent lookup; generic starts stay unchanged."""
    if creation is None:
        return
    if not isinstance(creation, WorkflowDriverCreation):
        raise ValueError(_INVALID_CREATION)
    if isinstance(creation, WorkflowChildCreation) and creation.parent.computer != computer:
        raise ValueError(_PARENT_UNAVAILABLE)
    if initiator_id is not None:
        relayed = get_relayed_caller()
        if initiator_computer != computer or (relayed is not None and relayed.computer != computer):
            raise ValueError(_PARENT_UNAVAILABLE)


def prepare_workflow_github_binding(
    session: Session, creation: WorkflowDriverCreation | None
) -> tuple[GitHubSessionBinding, GitHubWorkTarget] | None:
    """Select the public role assignment from actual session fields, never keys or caller-supplied actor facts."""
    validate_workflow_creation_address(creation, session.computer_name)
    if creation is None:
        return None
    if creation is not None and creation.item_id != session.working_slug:
        raise ValueError(_INVALID_CREATION)
    root = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
    if root is None:
        if creation is None:
            # An ordinary non-workflow session requests no binding; this does not select a local backend.
            return None
        raise ValueError(_INVALID_CREATION)
    selected = selected_workflow_store_backend(root)
    if selected is TodoStoreBackend.LOCAL:
        if creation is not None and creation.target is not None:
            raise ValueError(_INVALID_CREATION)
        return None
    if creation is None or creation.target is None or session.computer_name != config.computer.name:
        raise ValueError(_INVALID_CREATION)
    target = creation.target
    role = resolve_session_role(session.role, session.session_id)
    if (
        not isinstance(role, Role)
        or target.project_path != root
        or target.work_item != creation.item_id
        or target.branch is not None
        or target.base is not None
    ):
        raise ValueError(_INVALID_CREATION)
    assignment = github_actor_for_role(role.name)
    if assignment is None:
        raise ValueError(_INVALID_CREATION)
    binding = GitHubSessionBinding(
        session_id=session.session_id,
        role=role.name,
        assignment=assignment,
        workflow_parent=creation.parent if isinstance(creation, WorkflowChildCreation) else None,
    )
    return binding, target


async def validate_workflow_parent_in_transaction(
    db_session: AsyncSession,
    session: Session,
    creation: WorkflowDriverCreation | None,
    prepared: tuple[GitHubSessionBinding, GitHubWorkTarget] | None,
) -> None:
    """Consume the child owner's admitted relationship; perform no phase, holder or claim eligibility."""
    if not isinstance(creation, WorkflowChildCreation):
        return
    address = creation.parent
    if address.computer != session.computer_name or address.computer != config.computer.name:
        raise ValueError(_PARENT_UNAVAILABLE)
    parent = await db_session.get(db_models.Session, address.session_id)
    if (
        parent is None
        or parent.computer_name != address.computer
        or parent.closed_at is not None
        or parent.deleted_at is not None
    ):
        raise ValueError(_PARENT_UNAVAILABLE)
    if prepared is None:
        return
    binding, target = prepared
    row = await db_session.get(db_models.GitHubSessionBindingRow, address.session_id)
    if row is None or row.native_target_json is None:
        raise ValueError(_PARENT_UNAVAILABLE)
    parent_binding = GitHubSessionBinding.model_validate_json(row.binding_json)
    parent_target = GitHubWorkTarget.model_validate_json(row.native_target_json)
    role = resolve_session_role(parent.role, address.session_id)
    if (
        not isinstance(role, Role)
        or parent_binding.session_id != parent.session_id
        or parent_binding.role is not role.name
        or parent.working_slug != parent_target.work_item
        or parent_target.repository_id != target.repository_id
        or parent_target.repository.casefold() != target.repository.casefold()
        or parent_target.work_item != target.work_item
        or parent_target.issue_number != target.issue_number
        or not parent.project_path
        or resolve_owning_checkout(Path(parent.project_path)) != target.project_path
        or parent_target.project_path != target.project_path
        or parent_binding.assignment.app_id == binding.assignment.app_id
        or parent_binding.assignment.actor.id == binding.assignment.actor.id
        or parent_binding.assignment.actor.node_id == binding.assignment.actor.node_id
    ):
        raise ValueError(_PARENT_MISMATCH)

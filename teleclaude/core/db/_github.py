"""Session-owned persistence for fixed GitHub actor/work assignments."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import col

from teleclaude.core import db_models
from teleclaude.core.roles import Role, resolve_session_role
from teleclaude.types.github_binding import GitHubActorAssignment, GitHubSessionBinding, GitHubWorkTarget


class GitHubBindingRefusal(StrEnum):
    """Assignment conditions that establish no usable actor binding."""

    SESSION_UNAVAILABLE = "session_unavailable"
    ROLE_UNRESOLVED = "role_unresolved"
    TARGET_MISMATCH = "target_mismatch"
    PARENT_UNAVAILABLE = "parent_unavailable"
    PARENT_ACTOR_UNBOUND = "parent_actor_unbound"
    ACTOR_COLLISION = "actor_collision"
    ASSIGNMENT_CONFLICT = "assignment_conflict"
    ACTOR_UNBOUND = "actor_unbound"


class GitHubBindingRefused(ValueError):
    """An assignment was refused without changing a stored actor."""

    def __init__(self, reason: GitHubBindingRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


class DbGitHubMixin:
    """Persist assignments through the existing session database transaction."""

    async def get_github_session_binding(self, session_id: str) -> GitHubSessionBinding | None:
        """Read the durable assignment without selecting another actor."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
        return GitHubSessionBinding.model_validate_json(row.binding_json) if row is not None else None

    async def assign_github_actor(self, session_id: str, assignment: GitHubActorAssignment) -> GitHubSessionBinding:
        """Fix an infrastructure-provided actor to the actual session/work binding."""
        async with self._session() as db_session:
            session = await db_session.get(db_models.Session, session_id)
            if session is None or session.closed_at is not None or session.deleted_at is not None:
                raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
            role = resolve_session_role(session.role, session_id)
            if not isinstance(role, Role):
                raise GitHubBindingRefused(GitHubBindingRefusal.ROLE_UNRESOLVED)
            if session.initiator_session_id is not None:
                parent = await db_session.get(db_models.Session, session.initiator_session_id)
                if parent is None or parent.computer_name != session.computer_name:
                    raise GitHubBindingRefused(GitHubBindingRefusal.PARENT_UNAVAILABLE)
                if parent.role is not None:
                    parent_role = resolve_session_role(parent.role, parent.session_id)
                    if not isinstance(parent_role, Role):
                        raise GitHubBindingRefused(GitHubBindingRefusal.PARENT_UNAVAILABLE)
                    parent_row = await db_session.get(db_models.GitHubSessionBindingRow, parent.session_id)
                    if parent_row is None:
                        raise GitHubBindingRefused(GitHubBindingRefusal.PARENT_ACTOR_UNBOUND)
                    parent_binding = GitHubSessionBinding.model_validate_json(parent_row.binding_json)
                    if parent_binding.session_id != parent.session_id or parent_binding.role is not parent_role.name:
                        raise GitHubBindingRefused(GitHubBindingRefusal.PARENT_UNAVAILABLE)
                    parent_actor = parent_binding.assignment.actor
                    if (
                        parent_binding.assignment.app_id == assignment.app_id
                        or parent_actor.id == assignment.actor.id
                        or parent_actor.node_id == assignment.actor.node_id
                    ):
                        raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_COLLISION)
            binding = GitHubSessionBinding(session_id=session_id, role=role.name, assignment=assignment)
            statement = sqlite_insert(db_models.GitHubSessionBindingRow).values(
                session_id=session_id, binding_json=binding.model_dump_json()
            )
            await db_session.exec(statement.on_conflict_do_nothing())
            await db_session.commit()
            stored = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
            if stored is None or GitHubSessionBinding.model_validate_json(stored.binding_json) != binding:
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSIGNMENT_CONFLICT)
        return binding

    async def get_github_native_target(self, session_id: str) -> GitHubWorkTarget | None:
        """Read the work owner's native target separately from the session's actor."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
        if row is None or row.native_target_json is None:
            return None
        return GitHubWorkTarget.model_validate_json(row.native_target_json)

    async def bind_github_native_target(self, session_id: str, target: GitHubWorkTarget) -> None:
        """Retain an owner-supplied native scope without changing actor assignment."""
        async with self._session() as db_session:
            session = await db_session.get(db_models.Session, session_id)
            if session is None or session.closed_at is not None or session.deleted_at is not None:
                raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
            if (
                not session.project_path
                or Path(session.project_path).resolve() != target.project_path.resolve()
                or session.working_slug != target.work_item
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
            if row is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_UNBOUND)
            binding = GitHubSessionBinding.model_validate_json(row.binding_json)
            if binding.session_id != session_id or binding.role.value != session.role:
                raise GitHubBindingRefused(GitHubBindingRefusal.ROLE_UNRESOLVED)
            statement = (
                update(db_models.GitHubSessionBindingRow)
                .where(
                    db_models.GitHubSessionBindingRow.session_id == session_id,
                    col(db_models.GitHubSessionBindingRow.native_target_json).is_(None),
                )
                .values(native_target_json=target.model_dump_json())
            )
            await db_session.exec(statement)
            await db_session.commit()
            stored = await db_session.get(db_models.GitHubSessionBindingRow, session_id, populate_existing=True)
            if (
                stored is None
                or stored.native_target_json is None
                or GitHubWorkTarget.model_validate_json(stored.native_target_json) != target
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)

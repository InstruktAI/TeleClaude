"""Session-owned persistence for fixed GitHub actor/work assignments."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from teleclaude.core import db_models
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.core.roles import Role, resolve_session_role
from teleclaude.types.github_binding import GitHubActorAssignment, GitHubSessionBinding, GitHubWorkTarget
from teleclaude.types.github_posting import GitHubObjectAssociation, GitHubObjectRef, NativeGitHubPostSource


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
    ASSOCIATION_CONFLICT = "association_conflict"


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
        """Check an already complete identical creation binding; never complete an existing session later."""
        async with self._session() as db_session:
            session = await db_session.get(db_models.Session, session_id)
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
            if session is None or session.closed_at is not None or session.deleted_at is not None:
                raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
            if row is None or row.native_target_json is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_UNBOUND)
            binding = GitHubSessionBinding.model_validate_json(row.binding_json)
            target = GitHubWorkTarget.model_validate_json(row.native_target_json)
            role = resolve_session_role(session.role, session_id)
            if (
                not isinstance(role, Role)
                or binding.role is not role.name
                or binding.session_id != session_id
                or binding.assignment.app_id != assignment.app_id
                or not binding.assignment.actor.same_account(assignment.actor)
                or target.work_item != session.working_slug
                or not session.project_path
                or resolve_owning_checkout(Path(session.project_path)) != target.project_path
            ):
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
        """Check complete identical target state; partial legacy rows cannot acquire authority here."""
        async with self._session() as db_session:
            session = await db_session.get(db_models.Session, session_id)
            if session is None or session.closed_at is not None or session.deleted_at is not None:
                raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
            if row is None or row.native_target_json is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_UNBOUND)
            binding = GitHubSessionBinding.model_validate_json(row.binding_json)
            if (
                binding.session_id != session_id
                or binding.role.value != session.role
                or GitHubWorkTarget.model_validate_json(row.native_target_json) != target
                or not session.project_path
                or resolve_owning_checkout(Path(session.project_path)) != target.project_path
                or session.working_slug != target.work_item
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)

    async def get_github_object_association(self, ref: GitHubObjectRef) -> GitHubObjectAssociation | None:
        """Read exact creation provenance; envelopes and last-comment selection are not inputs."""
        key = (ref.repository_id, ref.container_number, ref.kind.value, ref.provider_id)
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubObjectAssociationRow, key)
        if row is None:
            return None
        stored = GitHubObjectAssociation.model_validate_json(row.creation_json)
        if stored.object != ref:
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        return stored

    async def record_github_object_association(self, association: GitHubObjectAssociation) -> GitHubObjectAssociation:
        """Record verified creation once; a conflict never replaces another producer's facts."""
        ref = association.object
        key = (ref.repository_id, ref.container_number, ref.kind.value, ref.provider_id)
        statement = sqlite_insert(db_models.GitHubObjectAssociationRow).values(
            repository_id=ref.repository_id,
            container_number=ref.container_number,
            object_kind=ref.kind.value,
            provider_id=ref.provider_id,
            creation_json=association.model_dump_json(),
        )
        async with self._session() as db_session:
            binding_row = await db_session.get(db_models.GitHubSessionBindingRow, association.session_id)
            if binding_row is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_UNBOUND)
            binding = GitHubSessionBinding.model_validate_json(binding_row.binding_json)
            if (
                binding.session_id != association.session_id
                or binding.role is not association.role
                or not binding.assignment.actor.same_account(association.actor)
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            if isinstance(association.source, NativeGitHubPostSource):
                if binding_row.native_target_json is None:
                    raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
                target = GitHubWorkTarget.model_validate_json(binding_row.native_target_json)
                if target.repository_id != ref.repository_id or target.issue_number != association.work_issue_number:
                    raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
            await db_session.exec(statement.on_conflict_do_nothing())
            await db_session.commit()
            row = await db_session.get(db_models.GitHubObjectAssociationRow, key)
            if row is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            stored = GitHubObjectAssociation.model_validate_json(row.creation_json)
            if not stored.same_creation(association):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        return stored

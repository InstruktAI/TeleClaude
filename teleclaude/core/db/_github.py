"""Session-owned persistence for fixed GitHub actor/work assignments."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import func, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from teleclaude.config.machine import config
from teleclaude.core import db_models
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.core.roles import Role, RoleName, resolve_session_role
from teleclaude.types.github_binding import (
    GitHubActorAssignment,
    GitHubOriginBindingFacts,
    GitHubSessionBinding,
    GitHubWorkTarget,
)
from teleclaude.types.github_posting import (
    GitHubObjectAssociation,
    GitHubObjectKind,
    GitHubObjectMutation,
    GitHubObjectMutationRecord,
    GitHubObjectRef,
    GitHubPullRequestDescriptionMutation,
    NativeGitHubPostSource,
)
from teleclaude.types.github_publication import GitHubPushProof

_MUTATION_APPEND_PATH = "$[#]"
_JSON_ARRAY = "array"
_MUTATIONS_ADAPTER = TypeAdapter(tuple[GitHubObjectMutationRecord, ...])
_PUSH_PROOFS_ADAPTER = TypeAdapter(tuple[GitHubPushProof, ...])
_HEADS = "refs/heads/"


def _unique_association(rows: Sequence[db_models.GitHubObjectAssociationRow]) -> GitHubObjectAssociation | None:
    if not rows:
        return None
    if len(rows) != 1:
        raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
    row = rows[0]
    value = GitHubObjectAssociation.model_validate_json(row.creation_json)
    ref = value.object
    if (ref.repository_id, ref.container_number, ref.kind.value, ref.provider_id) != (
        row.repository_id,
        row.container_number,
        row.object_kind,
        row.provider_id,
    ):
        raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
    return value


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


def _require_remote_creation(association: GitHubObjectAssociation, origin: GitHubOriginBindingFacts) -> None:
    """The posting owner supplies freshly read origin facts, never a foreign local binding row."""
    ref, binding, target = association.object, origin.binding, origin.target
    if (
        origin.computer == config.computer.name
        or isinstance(association.source, NativeGitHubPostSource)
        or ref.kind is not GitHubObjectKind.ISSUE_COMMENT
        or ref.repository_id != target.repository_id
        or ref.container_number != target.issue_number
        or association.work_issue_number != target.issue_number
        or association.session_id != binding.session_id
        or association.role is not binding.role
        or not association.actor.same_account(binding.assignment.actor)
        or association.producer_principal != origin.principal
        or association.producer_computer != origin.computer
        or association.producer_target != target
    ):
        raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)


class DbGitHubMixin:
    """Persist assignments through the existing session database transaction."""

    async def get_github_push_proofs(self, session_id: str) -> tuple[GitHubPushProof, ...]:
        """Read retained producing-session evidence, without reconstructing it from provider discovery."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
        if row is None:
            return ()
        proofs = _PUSH_PROOFS_ADAPTER.validate_json(row.push_proofs_json)
        if any(proof.binding.session_id != session_id for proof in proofs):
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        return proofs

    async def record_github_push_proof(self, proof: GitHubPushProof) -> GitHubPushProof:
        """Append actual-child/observed corroboration under the unchanged authoritative binding."""
        session_id = proof.binding.session_id
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubSessionBindingRow, session_id)
            session = await db_session.get(db_models.Session, session_id)
            if row is None or row.native_target_json is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_UNBOUND)
            if session is None or session.closed_at is not None or session.deleted_at is not None:
                raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
            binding = GitHubSessionBinding.model_validate_json(row.binding_json)
            target = GitHubWorkTarget.model_validate_json(row.native_target_json)
            project = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
            if (
                binding != proof.binding
                or target != proof.target
                or session.role != binding.role.value
                or target.work_item != session.working_slug
                or project is None
                or resolve_owning_checkout(target.project_path) != project
                or not target.branch
                or not target.base
                or target.branch == target.base
                or proof.ref != _HEADS + target.branch
                or proof.before == proof.after
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            existing = _PUSH_PROOFS_ADAPTER.validate_json(row.push_proofs_json)
            if proof in existing:
                return proof
            statement = (
                update(db_models.GitHubSessionBindingRow)
                .where(
                    db_models.GitHubSessionBindingRow.session_id == session_id,
                    db_models.GitHubSessionBindingRow.binding_json == row.binding_json,
                    db_models.GitHubSessionBindingRow.native_target_json == row.native_target_json,
                    func.json_valid(db_models.GitHubSessionBindingRow.push_proofs_json) == 1,
                    func.json_type(db_models.GitHubSessionBindingRow.push_proofs_json) == _JSON_ARRAY,
                )
                .values(
                    push_proofs_json=func.json_insert(
                        db_models.GitHubSessionBindingRow.push_proofs_json,
                        _MUTATION_APPEND_PATH,
                        func.json(proof.model_dump_json()),
                    )
                )
                .execution_options(synchronize_session=False)
            )
            result = await db_session.exec(statement)
            if result.rowcount != 1:
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            await db_session.commit()
        return proof

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

    async def find_github_object_association(
        self,
        repository_id: int,
        kind: GitHubObjectKind,
        provider_id: int,
    ) -> GitHubObjectAssociation | None:
        """Resolve one explicit provider object within its repository/kind; ambiguity is no authority."""
        async with self._session() as db_session:
            rows = await db_session.exec(
                select(db_models.GitHubObjectAssociationRow)
                .where(
                    db_models.GitHubObjectAssociationRow.repository_id == repository_id,
                    db_models.GitHubObjectAssociationRow.object_kind == kind.value,
                    db_models.GitHubObjectAssociationRow.provider_id == provider_id,
                )
                .limit(2)
            )
            return _unique_association(rows.all())

    async def find_github_pr_association(self, repository_id: int, number: int) -> GitHubObjectAssociation | None:
        """Read the one retained PR relationship, without reconstructing it from branch or prose."""
        async with self._session() as db_session:
            rows = await db_session.exec(
                select(db_models.GitHubObjectAssociationRow)
                .where(
                    db_models.GitHubObjectAssociationRow.repository_id == repository_id,
                    db_models.GitHubObjectAssociationRow.object_kind == GitHubObjectKind.PULL_REQUEST.value,
                    db_models.GitHubObjectAssociationRow.container_number == number,
                )
                .limit(2)
            )
            return _unique_association(rows.all())

    async def _check_pr_relationship(
        self,
        db_session: AsyncSession,
        scope: GitHubObjectAssociation,
        target: GitHubWorkTarget,
    ) -> None:
        """A historical creator can be closed; its exact immutable PR/work relationship must remain."""
        ref = scope.object
        rows = await db_session.exec(
            select(db_models.GitHubObjectAssociationRow)
            .where(
                db_models.GitHubObjectAssociationRow.repository_id == ref.repository_id,
                db_models.GitHubObjectAssociationRow.object_kind == GitHubObjectKind.PULL_REQUEST.value,
                db_models.GitHubObjectAssociationRow.container_number == ref.container_number,
            )
            .limit(2)
        )
        current = _unique_association(rows.all())
        if (
            ref.kind is not GitHubObjectKind.PULL_REQUEST
            or ref.repository_id != target.repository_id
            or scope.work_issue_number != target.issue_number
            or scope.pull_request is None
            or current is None
            or not current.same_creation(scope)
        ):
            raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)

    async def _check_native_conversation_writer(
        self,
        db_session: AsyncSession,
        association: GitHubObjectAssociation,
        pr_scope: GitHubObjectAssociation | None,
    ) -> None:
        session = await db_session.get(db_models.Session, association.session_id)
        row = await db_session.get(db_models.GitHubSessionBindingRow, association.session_id)
        if (
            session is None
            or session.closed_at is not None
            or session.deleted_at is not None
            or row is None
            or row.native_target_json is None
        ):
            raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
        binding = GitHubSessionBinding.model_validate_json(row.binding_json)
        target = GitHubWorkTarget.model_validate_json(row.native_target_json)
        project = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
        if (
            binding.session_id != session.session_id
            or binding.role is not association.role
            or session.role != association.role.value
            or not binding.assignment.actor.same_account(association.actor)
            or target.repository_id != association.object.repository_id
            or target.issue_number != association.work_issue_number
            or session.working_slug != target.work_item
            or project is None
            or resolve_owning_checkout(target.project_path) != project
        ):
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        if pr_scope is not None:
            await self._check_pr_relationship(db_session, pr_scope, target)
        expected = pr_scope.object.container_number if pr_scope is not None else target.issue_number
        if association.object.container_number != expected:
            raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
        rows = await db_session.exec(
            select(db_models.GitHubObjectAssociationRow)
            .where(
                db_models.GitHubObjectAssociationRow.repository_id == association.object.repository_id,
                db_models.GitHubObjectAssociationRow.object_kind == association.object.kind.value,
                db_models.GitHubObjectAssociationRow.provider_id == association.object.provider_id,
            )
            .limit(2)
        )
        existing = _unique_association(rows.all())
        if existing is not None and not existing.same_creation(association):
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)

    async def record_github_object_association(
        self,
        association: GitHubObjectAssociation,
        *,
        pr_scope: GitHubObjectAssociation | None = None,
        verified_origin: GitHubOriginBindingFacts | None = None,
    ) -> GitHubObjectAssociation:
        """Record verified creation once; a conflict never replaces another producer's facts."""
        ref = association.object
        if ref.kind is GitHubObjectKind.PULL_REQUEST and isinstance(association.source, NativeGitHubPostSource):
            # Native PR creation has its own proof/driver-aware transaction; generic recording supplies neither.
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        key = (ref.repository_id, ref.container_number, ref.kind.value, ref.provider_id)
        statement = sqlite_insert(db_models.GitHubObjectAssociationRow).values(
            repository_id=ref.repository_id,
            container_number=ref.container_number,
            object_kind=ref.kind.value,
            provider_id=ref.provider_id,
            creation_json=association.model_dump_json(),
        )
        async with self._session() as db_session:
            if verified_origin is not None:
                if pr_scope is not None:
                    raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
                _require_remote_creation(association, verified_origin)
            else:
                if any(
                    value is not None
                    for value in (
                        association.producer_principal,
                        association.producer_computer,
                        association.producer_target,
                    )
                ):
                    raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
                if isinstance(association.source, NativeGitHubPostSource) and ref.kind in (
                    GitHubObjectKind.ISSUE_COMMENT,
                    GitHubObjectKind.REVIEW,
                    GitHubObjectKind.REVIEW_COMMENT,
                ):
                    if ref.kind in (GitHubObjectKind.REVIEW, GitHubObjectKind.REVIEW_COMMENT) and pr_scope is None:
                        raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
                    await self._check_native_conversation_writer(db_session, association, pr_scope)
                elif pr_scope is not None:
                    raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
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
                    if (
                        target.repository_id != ref.repository_id
                        or target.issue_number != association.work_issue_number
                    ):
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

    async def get_github_object_mutations(self, ref: GitHubObjectRef) -> tuple[GitHubObjectMutationRecord, ...]:
        """Read recorded observations without asserting provider order or current state."""
        key = (ref.repository_id, ref.container_number, ref.kind.value, ref.provider_id)
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubObjectAssociationRow, key)
        if row is None:
            return ()
        values = _MUTATIONS_ADAPTER.validate_json(row.mutations_json)
        if any(value.object != ref for value in values):
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        return values

    async def _check_github_pr_owner(
        self,
        db_session: AsyncSession,
        proof: GitHubPushProof,
        parent_binding: GitHubSessionBinding,
    ) -> GitHubWorkTarget:
        """Check current local ownership and retained push evidence in the attribution transaction."""
        binding = proof.binding
        session = await db_session.get(db_models.Session, binding.session_id)
        parent = await db_session.get(db_models.Session, parent_binding.session_id)
        row = await db_session.get(db_models.GitHubSessionBindingRow, binding.session_id)
        parent_row = await db_session.get(db_models.GitHubSessionBindingRow, parent_binding.session_id)
        if (
            session is None
            or parent is None
            or row is None
            or parent_row is None
            or row.native_target_json is None
            or parent_row.native_target_json is None
            or session.closed_at is not None
            or session.deleted_at is not None
            or parent.closed_at is not None
            or parent.deleted_at is not None
            or session.initiator_session_id != parent.session_id
            or session.computer_name != parent.computer_name
            or session.role != RoleName.BUILDER.value
            or binding.role is not RoleName.BUILDER
            or parent.role != RoleName.WORK_ORCHESTRATOR.value
            or parent_binding.role is not RoleName.WORK_ORCHESTRATOR
            or GitHubSessionBinding.model_validate_json(row.binding_json) != binding
            or GitHubSessionBinding.model_validate_json(parent_row.binding_json) != parent_binding
            or binding.assignment.app_id == parent_binding.assignment.app_id
            or binding.assignment.actor.id == parent_binding.assignment.actor.id
            or binding.assignment.actor.node_id == parent_binding.assignment.actor.node_id
            or proof not in _PUSH_PROOFS_ADAPTER.validate_json(row.push_proofs_json)
        ):
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        target = GitHubWorkTarget.model_validate_json(row.native_target_json)
        parent_target = GitHubWorkTarget.model_validate_json(parent_row.native_target_json)
        project = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
        parent_project = resolve_owning_checkout(Path(parent.project_path)) if parent.project_path else None
        if (
            target != proof.target
            or not target.branch
            or not target.base
            or target.branch == target.base
            or proof.ref != _HEADS + target.branch
            or proof.before == proof.after
            or session.working_slug != target.work_item
            or parent.working_slug != parent_target.work_item
            or parent_target.work_item != target.work_item
            or parent_target.repository_id != target.repository_id
            or parent_target.repository.casefold() != target.repository.casefold()
            or parent_target.issue_number != target.issue_number
            or project is None
            or parent_project != project
            or resolve_owning_checkout(target.project_path) != project
            or resolve_owning_checkout(parent_target.project_path) != project
        ):
            raise GitHubBindingRefused(GitHubBindingRefusal.TARGET_MISMATCH)
        return target

    async def record_github_pr_creation(
        self,
        creation: GitHubObjectAssociation,
        *,
        proof: GitHubPushProof,
        parent: GitHubSessionBinding,
    ) -> GitHubObjectAssociation:
        """Retain a verified PR creator once; discovery cannot reconstruct missing provenance."""
        ref = creation.object
        async with self._session() as db_session:
            target = await self._check_github_pr_owner(db_session, proof, parent)
            if (
                ref.kind is not GitHubObjectKind.PULL_REQUEST
                or creation.pull_request is None
                or not isinstance(creation.source, NativeGitHubPostSource)
                or ref.repository_id != target.repository_id
                or creation.work_issue_number != target.issue_number
                or creation.session_id != proof.binding.session_id
                or creation.role is not RoleName.BUILDER
                or not creation.actor.same_account(proof.binding.assignment.actor)
                or creation.pull_request.head_ref != target.branch
                or creation.pull_request.base_ref != target.base
                or creation.pull_request.head_sha != proof.after
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            statement = sqlite_insert(db_models.GitHubObjectAssociationRow).values(
                repository_id=ref.repository_id,
                container_number=ref.container_number,
                object_kind=ref.kind.value,
                provider_id=ref.provider_id,
                creation_json=creation.model_dump_json(),
            )
            await db_session.exec(statement.on_conflict_do_nothing())
            await db_session.commit()
            stored = await db_session.get(
                db_models.GitHubObjectAssociationRow,
                (
                    ref.repository_id,
                    ref.container_number,
                    ref.kind.value,
                    ref.provider_id,
                ),
            )
            if stored is None or not GitHubObjectAssociation.model_validate_json(stored.creation_json).same_creation(
                creation
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        return creation

    async def record_github_pr_description(
        self,
        mutation: GitHubPullRequestDescriptionMutation,
        *,
        creation: GitHubObjectAssociation,
        proof: GitHubPushProof,
        parent: GitHubSessionBinding,
    ) -> GitHubPullRequestDescriptionMutation:
        """Append later PR description attribution while comparing the exact original creator row."""
        ref = mutation.object
        async with self._session() as db_session:
            target = await self._check_github_pr_owner(db_session, proof, parent)
            row = await db_session.get(
                db_models.GitHubObjectAssociationRow,
                (
                    ref.repository_id,
                    ref.container_number,
                    ref.kind.value,
                    ref.provider_id,
                ),
            )
            if (
                row is None
                or not GitHubObjectAssociation.model_validate_json(row.creation_json).same_creation(creation)
                or creation.object != ref
                or creation.pull_request is None
                or not isinstance(creation.source, NativeGitHubPostSource)
                or creation.session_id != proof.binding.session_id
                or mutation.session_id != creation.session_id
                or creation.role is not RoleName.BUILDER
                or mutation.role is not creation.role
                or not creation.actor.same_account(proof.binding.assignment.actor)
                or not mutation.actor.same_account(creation.actor)
                or ref.repository_id != target.repository_id
                or creation.work_issue_number != target.issue_number
                or creation.pull_request.head_ref != target.branch
                or creation.pull_request.base_ref != target.base
                or mutation.head_sha != proof.after
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            statement = (
                update(db_models.GitHubObjectAssociationRow)
                .where(
                    db_models.GitHubObjectAssociationRow.repository_id == ref.repository_id,
                    db_models.GitHubObjectAssociationRow.container_number == ref.container_number,
                    db_models.GitHubObjectAssociationRow.object_kind == ref.kind.value,
                    db_models.GitHubObjectAssociationRow.provider_id == ref.provider_id,
                    db_models.GitHubObjectAssociationRow.creation_json == row.creation_json,
                    func.json_valid(db_models.GitHubObjectAssociationRow.mutations_json) == 1,
                    func.json_type(db_models.GitHubObjectAssociationRow.mutations_json) == _JSON_ARRAY,
                )
                .values(
                    mutations_json=func.json_insert(
                        db_models.GitHubObjectAssociationRow.mutations_json,
                        _MUTATION_APPEND_PATH,
                        func.json(mutation.model_dump_json()),
                    )
                )
                .execution_options(synchronize_session=False)
            )
            result = await db_session.exec(statement)
            if result.rowcount != 1:
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            await db_session.commit()
        return mutation

    async def record_github_object_mutation(
        self,
        mutation: GitHubObjectMutation,
        *,
        creation: GitHubObjectAssociation,
        pr_scope: GitHubObjectAssociation | None = None,
    ) -> GitHubObjectMutation:
        """Append confirmed native evidence atomically, preserving the exact immutable creator row."""
        ref = mutation.object
        if (
            not isinstance(creation.source, NativeGitHubPostSource)
            or creation.object != ref
            or creation.session_id != mutation.session_id
            or creation.role is not mutation.role
            or not creation.actor.same_account(mutation.actor)
            or (
                ref.kind is GitHubObjectKind.REVIEW
                and (pr_scope is None or mutation.reviewed_sha != creation.reviewed_sha)
            )
            or (
                ref.kind is GitHubObjectKind.REVIEW_COMMENT
                and (
                    pr_scope is None
                    or creation.review_comment is None
                    or mutation.review_comment is None
                    or mutation.review_comment.in_reply_to_id != creation.review_comment.in_reply_to_id
                )
            )
        ):
            raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
        key = (ref.repository_id, ref.container_number, ref.kind.value, ref.provider_id)
        async with self._session() as db_session:
            row = await db_session.get(db_models.GitHubObjectAssociationRow, key)
            session = await db_session.get(db_models.Session, mutation.session_id)
            binding_row = await db_session.get(db_models.GitHubSessionBindingRow, mutation.session_id)
            if row is None or GitHubObjectAssociation.model_validate_json(row.creation_json) != creation:
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            if session is None or session.closed_at is not None or session.deleted_at is not None:
                raise GitHubBindingRefused(GitHubBindingRefusal.SESSION_UNAVAILABLE)
            if binding_row is None or binding_row.native_target_json is None:
                raise GitHubBindingRefused(GitHubBindingRefusal.ACTOR_UNBOUND)
            binding = GitHubSessionBinding.model_validate_json(binding_row.binding_json)
            target = GitHubWorkTarget.model_validate_json(binding_row.native_target_json)
            if pr_scope is not None:
                await self._check_pr_relationship(db_session, pr_scope, target)
            expected = pr_scope.object.container_number if pr_scope is not None else target.issue_number
            project = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
            if (
                binding.session_id != mutation.session_id
                or session.role != mutation.role.value
                or binding.role is not mutation.role
                or not binding.assignment.actor.same_account(mutation.actor)
                or target.repository_id != ref.repository_id
                or expected != ref.container_number
                or target.issue_number != creation.work_issue_number
                or target.work_item != session.working_slug
                or project is None
                or resolve_owning_checkout(target.project_path) != project
            ):
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            statement = (
                update(db_models.GitHubObjectAssociationRow)
                .where(
                    db_models.GitHubObjectAssociationRow.repository_id == ref.repository_id,
                    db_models.GitHubObjectAssociationRow.container_number == ref.container_number,
                    db_models.GitHubObjectAssociationRow.object_kind == ref.kind.value,
                    db_models.GitHubObjectAssociationRow.provider_id == ref.provider_id,
                    db_models.GitHubObjectAssociationRow.creation_json == row.creation_json,
                    func.json_valid(db_models.GitHubObjectAssociationRow.mutations_json) == 1,
                    func.json_type(db_models.GitHubObjectAssociationRow.mutations_json) == _JSON_ARRAY,
                )
                .values(
                    mutations_json=func.json_insert(
                        db_models.GitHubObjectAssociationRow.mutations_json,
                        _MUTATION_APPEND_PATH,
                        func.json(mutation.model_dump_json()),
                    )
                )
                .execution_options(synchronize_session=False)
            )
            result = await db_session.exec(statement)
            if result.rowcount != 1:
                raise GitHubBindingRefused(GitHubBindingRefusal.ASSOCIATION_CONFLICT)
            await db_session.commit()
        return mutation

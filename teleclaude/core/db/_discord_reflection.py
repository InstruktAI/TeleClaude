"""Database adapter for integration-owned Discord reflection state."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select

from teleclaude.core import db_models
from teleclaude.core.integration.discord_admin_state import (
    DiscordArtifactKind,
    DiscordProvider,
    DiscordReflectionRecord,
    DiscordReflectionScope,
    DiscordScopeKind,
    DiscordSharedChildKind,
    DiscordSharedThreadClaim,
    DiscordSharedThreadClaimResult,
    DiscordThreadClaimActivation,
    DiscordThreadClaimInventoryItem,
    DiscordThreadClaimLifecycle,
    DiscordThreadClaimMemberState,
    DiscordThreadClaimOutcome,
    DiscordThreadOrphanCandidate,
    DiscordThreadReconciliationEpochPhase,
)


class DbDiscordReflectionMixin:
    """Persist Discord reflection records without leaking SQL rows to adapters."""

    async def get_discord_reflection(self, logical_key: str) -> DiscordReflectionRecord | None:
        """Read one Discord reflection record by its stable logical key."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.DiscordReflectionRow, (DiscordProvider.DISCORD.value, logical_key))
        return _to_record(row) if row is not None else None

    async def list_discord_reflections(
        self, scope: DiscordReflectionScope | None = None
    ) -> list[DiscordReflectionRecord]:
        """List records, optionally narrowed to one integration-owned scope."""
        statement = select(db_models.DiscordReflectionRow).where(
            db_models.DiscordReflectionRow.provider == DiscordProvider.DISCORD.value
        )
        if scope is not None:
            statement = statement.where(
                db_models.DiscordReflectionRow.scope_kind == scope.kind.value,
                db_models.DiscordReflectionRow.scope_value == scope.value,
            )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [_to_record(row) for row in rows]

    async def upsert_discord_reflection(self, record: DiscordReflectionRecord) -> None:
        """Create or replace one observed provider binding by provider and logical key."""
        statement = sqlite_insert(db_models.DiscordReflectionRow).values(
            provider=record.provider.value,
            logical_key=record.logical_key,
            artifact_kind=record.artifact_kind.value,
            scope_kind=record.scope.kind.value,
            scope_value=record.scope.value,
            provider_id=record.provider_id,
            parent_provider_id=record.parent_provider_id,
            metadata_json=record.metadata_json,
            verified_at=record.verified_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["provider", "logical_key"],
            set_={
                "artifact_kind": statement.excluded.artifact_kind,
                "scope_kind": statement.excluded.scope_kind,
                "scope_value": statement.excluded.scope_value,
                "provider_id": statement.excluded.provider_id,
                "parent_provider_id": statement.excluded.parent_provider_id,
                "metadata_json": statement.excluded.metadata_json,
                "verified_at": statement.excluded.verified_at,
            },
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def touch_discord_reflection(self, logical_key: str, verified_at: datetime) -> None:
        """Advance the verified timestamp for an already-recorded artifact."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.DiscordReflectionRow, (DiscordProvider.DISCORD.value, logical_key))
            if row is None:
                return
            row.verified_at = verified_at
            db_session.add(row)
            await db_session.commit()

    async def delete_discord_reflection(self, logical_key: str) -> None:
        """Remove one reflection record so a later natural reconciliation can recreate it."""
        statement = delete(db_models.DiscordReflectionRow).where(
            db_models.DiscordReflectionRow.provider == DiscordProvider.DISCORD.value,
            db_models.DiscordReflectionRow.logical_key == logical_key,
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def observe_discord_shared_thread(
        self, claim: DiscordSharedThreadClaim, *, source_computer: str, enforce_owner: bool
    ) -> DiscordSharedThreadClaimResult:
        """Persist one authenticated contender and optionally resolve its singular owner."""
        if claim.computer != source_computer:
            return DiscordSharedThreadClaimResult(DiscordThreadClaimOutcome.REFUSED, None, None)
        await self.observe_discord_thread_claim_member(source_computer, protocol_generation=claim.protocol_generation)
        contender = sqlite_insert(db_models.DiscordSharedThreadContenderRow).values(
            thread_id=claim.thread_id,
            computer=claim.computer,
            parent_id=claim.parent_id,
            child_kind=claim.kind.value,
            local_identity=claim.local_identity,
            lifecycle=claim.lifecycle.value,
            protocol_generation=claim.protocol_generation,
        )
        contender = contender.on_conflict_do_update(
            index_elements=["thread_id", "computer"],
            set_={
                "parent_id": contender.excluded.parent_id,
                "child_kind": contender.excluded.child_kind,
                "local_identity": contender.excluded.local_identity,
                "lifecycle": contender.excluded.lifecycle,
                "protocol_generation": contender.excluded.protocol_generation,
            },
        )
        async with self._session() as db_session:
            await db_session.exec(contender)
            if not enforce_owner:
                await db_session.commit()
                return DiscordSharedThreadClaimResult(DiscordThreadClaimOutcome.OBSERVED, None, None)
            owner = await db_session.get(db_models.DiscordSharedThreadOwnerRow, claim.thread_id)
            if owner is None:
                owner = db_models.DiscordSharedThreadOwnerRow(
                    thread_id=claim.thread_id,
                    parent_id=claim.parent_id,
                    child_kind=claim.kind.value,
                    owner_computer=claim.computer,
                    local_identity=claim.local_identity,
                    lifecycle=claim.lifecycle.value,
                    protocol_generation=claim.protocol_generation,
                )
                db_session.add(owner)
                await db_session.commit()
                return DiscordSharedThreadClaimResult(
                    DiscordThreadClaimOutcome.CLAIMED,
                    owner.owner_computer,
                    DiscordThreadClaimLifecycle(owner.lifecycle),
                )
            if owner.owner_computer != source_computer:
                await db_session.commit()
                return DiscordSharedThreadClaimResult(
                    DiscordThreadClaimOutcome.NOT_OWNER,
                    owner.owner_computer,
                    DiscordThreadClaimLifecycle(owner.lifecycle),
                )
            owner.lifecycle = claim.lifecycle.value
            owner.local_identity = claim.local_identity
            await db_session.commit()
            return DiscordSharedThreadClaimResult(
                DiscordThreadClaimOutcome.CLAIMED, owner.owner_computer, DiscordThreadClaimLifecycle(owner.lifecycle)
            )

    async def get_discord_shared_thread_owner(self, thread_id: int) -> DiscordSharedThreadClaim | None:
        """Read the durable owner claim for one shared Discord child, if any."""
        async with self._session() as db_session:
            owner = await db_session.get(db_models.DiscordSharedThreadOwnerRow, thread_id)
        if owner is None:
            return None
        return DiscordSharedThreadClaim(
            thread_id=owner.thread_id,
            parent_id=owner.parent_id,
            kind=DiscordSharedChildKind(owner.child_kind),
            computer=owner.owner_computer,
            local_identity=owner.local_identity,
            lifecycle=DiscordThreadClaimLifecycle(owner.lifecycle),
            protocol_generation=owner.protocol_generation,
        )

    async def observe_discord_thread_claim_member(self, computer: str, *, protocol_generation: int) -> None:
        """Retain a fleet member so temporary offline discovery cannot enable deletion."""
        statement = sqlite_insert(db_models.DiscordThreadClaimMemberRow).values(
            computer=computer,
            protocol_generation=protocol_generation,
            adoption_state=DiscordThreadClaimMemberState.OBSERVED.value,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["computer"],
            set_={"protocol_generation": protocol_generation},
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def complete_discord_thread_claim_inventory(
        self, computer: str, *, protocol_generation: int, epoch: int
    ) -> bool:
        """Mark one retained member complete only for the current master epoch."""
        async with self._session() as db_session:
            allocator = await db_session.get(db_models.DiscordThreadReconciliationEpochRow, protocol_generation)
            member = await db_session.get(db_models.DiscordThreadClaimMemberRow, computer)
            if allocator is None or member is None or allocator.current_epoch != epoch:
                return False
            member.protocol_generation = protocol_generation
            member.adoption_state = DiscordThreadClaimMemberState.ADOPTED.value
            member.inventory_completed_epoch = epoch
            db_session.add(member)
            await db_session.commit()
            return True

    async def replace_discord_thread_claim_inventory(
        self,
        computer: str,
        *,
        protocol_generation: int,
        epoch: int,
        items: tuple[DiscordThreadClaimInventoryItem, ...],
    ) -> bool:
        """Replace one member's full inventory atomically before marking its epoch complete."""
        async with self._session() as db_session:
            allocator = await db_session.get(db_models.DiscordThreadReconciliationEpochRow, protocol_generation)
            member = await db_session.get(db_models.DiscordThreadClaimMemberRow, computer)
            if allocator is None or member is None or allocator.current_epoch != epoch:
                return False
            statement = delete(db_models.DiscordThreadClaimInventoryItemRow).where(
                db_models.DiscordThreadClaimInventoryItemRow.computer == computer,
                db_models.DiscordThreadClaimInventoryItemRow.protocol_generation == protocol_generation,
                db_models.DiscordThreadClaimInventoryItemRow.inventory_epoch == epoch,
            )
            await db_session.exec(statement)
            for item in items:
                db_session.add(
                    db_models.DiscordThreadClaimInventoryItemRow(
                        computer=computer,
                        protocol_generation=protocol_generation,
                        inventory_epoch=epoch,
                        thread_id=item.thread_id,
                        parent_id=item.parent_id,
                        child_kind=item.kind.value,
                        local_identity=item.local_identity,
                        lifecycle=item.lifecycle.value,
                    )
                )
            member.protocol_generation = protocol_generation
            member.adoption_state = DiscordThreadClaimMemberState.ADOPTED.value
            member.inventory_completed_epoch = epoch
            db_session.add(member)
            await db_session.commit()
            return True

    async def open_discord_thread_reconciliation_epoch(self, *, protocol_generation: int) -> int:
        """Allocate one epoch or resume the extant open epoch after a restart."""
        async with self._session() as db_session:
            allocator = await db_session.get(db_models.DiscordThreadReconciliationEpochRow, protocol_generation)
            if allocator is not None and allocator.phase == DiscordThreadReconciliationEpochPhase.OPEN.value:
                return allocator.current_epoch
            next_epoch = 1 if allocator is None else allocator.current_epoch + 1
            if allocator is None:
                allocator = db_models.DiscordThreadReconciliationEpochRow(
                    protocol_generation=protocol_generation,
                    current_epoch=next_epoch,
                    phase=DiscordThreadReconciliationEpochPhase.OPEN.value,
                )
            else:
                allocator.current_epoch = next_epoch
                allocator.phase = DiscordThreadReconciliationEpochPhase.OPEN.value
            db_session.add(allocator)
            await db_session.commit()
            return next_epoch

    async def complete_discord_thread_reconciliation_epoch(self, *, protocol_generation: int, epoch: int) -> bool:
        """Close the named open epoch so the next open call allocates a fresh one.

        Idempotent: a second close of the same already-completed epoch is a
        no-op success, so concurrent shared-forum passes within one cleanup
        cycle cannot double-transition or skip a generation.
        """
        async with self._session() as db_session:
            allocator = await db_session.get(db_models.DiscordThreadReconciliationEpochRow, protocol_generation)
            if allocator is None or allocator.current_epoch != epoch:
                return False
            if allocator.phase == DiscordThreadReconciliationEpochPhase.COMPLETED.value:
                return True
            allocator.phase = DiscordThreadReconciliationEpochPhase.COMPLETED.value
            db_session.add(allocator)
            await db_session.commit()
            return True

    async def discord_thread_claim_activation(
        self, *, protocol_generation: int, live_members: frozenset[str], capability_members: frozenset[str]
    ) -> DiscordThreadClaimActivation:
        """Require every retained member's adoption and every live member's capability before enforcement."""
        statement = select(db_models.DiscordThreadClaimMemberRow).where(
            db_models.DiscordThreadClaimMemberRow.protocol_generation == protocol_generation
        )
        async with self._session() as db_session:
            members = tuple((await db_session.exec(statement)).all())
        retained = tuple(sorted(member.computer for member in members))
        adopted = bool(members) and all(
            member.adoption_state == DiscordThreadClaimMemberState.ADOPTED.value for member in members
        )
        live_capable = live_members <= capability_members
        return DiscordThreadClaimActivation(active=adopted and live_capable, retained_members=retained)

    async def advance_discord_thread_orphan_candidate(
        self, *, thread_id: int, parent_id: int, epoch: int
    ) -> DiscordThreadOrphanCandidate:
        """Advance one unclaimed child only when the caller supplies a completed epoch."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.DiscordThreadOrphanCandidateRow, thread_id)
            if row is None:
                row = db_models.DiscordThreadOrphanCandidateRow(
                    thread_id=thread_id,
                    parent_id=parent_id,
                    first_qualifying_epoch=epoch,
                    last_qualifying_epoch=epoch,
                    consecutive_complete_epochs=1,
                )
            elif row.last_qualifying_epoch != epoch - 1:
                row.parent_id = parent_id
                row.first_qualifying_epoch = epoch
                row.last_qualifying_epoch = epoch
                row.consecutive_complete_epochs = 1
            else:
                row.last_qualifying_epoch = epoch
                row.consecutive_complete_epochs += 1
            db_session.add(row)
            await db_session.commit()
            return DiscordThreadOrphanCandidate(row.thread_id, row.parent_id, row.consecutive_complete_epochs)

    async def reset_discord_thread_orphan_candidate(self, *, thread_id: int) -> None:
        """Discard orphan proof when a contender, owner, or incomplete epoch reappears."""
        statement = delete(db_models.DiscordThreadOrphanCandidateRow).where(
            db_models.DiscordThreadOrphanCandidateRow.thread_id == thread_id
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def completed_discord_thread_claim_epoch(self, *, protocol_generation: int) -> int | None:
        """Return the current epoch only after every retained member completed that exact epoch."""
        async with self._session() as db_session:
            epoch = await db_session.get(db_models.DiscordThreadReconciliationEpochRow, protocol_generation)
            if epoch is None:
                return None
            statement = select(db_models.DiscordThreadClaimMemberRow).where(
                db_models.DiscordThreadClaimMemberRow.protocol_generation == protocol_generation
            )
            members = tuple((await db_session.exec(statement)).all())
        if not members or any(member.inventory_completed_epoch != epoch.current_epoch for member in members):
            return None
        return epoch.current_epoch


def _to_record(row: db_models.DiscordReflectionRow) -> DiscordReflectionRecord:
    """Translate one database row into the integration-owned DTO."""
    return DiscordReflectionRecord(
        provider=DiscordProvider(row.provider),
        logical_key=row.logical_key,
        artifact_kind=DiscordArtifactKind(row.artifact_kind),
        scope=DiscordReflectionScope(kind=DiscordScopeKind(row.scope_kind), value=row.scope_value),
        provider_id=row.provider_id,
        parent_provider_id=row.parent_provider_id,
        metadata_json=row.metadata_json,
        verified_at=row.verified_at,
    )

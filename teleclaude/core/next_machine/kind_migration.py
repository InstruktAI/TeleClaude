"""Todo kind migration semantics for the update facade."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_TASK_PLAN,
)
from teleclaude.core.next_machine.kinds import KIND_ENTRY_PHASE, canonical_kind
from teleclaude.core.next_machine.provenance import clear_artifact_provenance
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.types.todo_kind import TODO_KIND_BUG, TODO_KIND_FEATURE, TODO_KIND_TASK

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

_ORPHAN_CHECK_ORDER = (
    ARTIFACT_PRD,
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_TASK_PLAN,
    ARTIFACT_IMPLEMENTATION_PLAN,
)


class KindMigrationResult(TypedDict):
    slug: str
    kind: str
    lifecycle_phase: str
    orphaned_artifacts: list[str]
    warnings: list[str]
    folded_artifact: NotRequired[str]


class KindMigrationRequiresForce(StateMutationError):
    """Raised when a kind migration would orphan artifacts without force."""

    def __init__(self, *, current_kind: str | None, target_kind: str, orphaned_artifacts: list[str]) -> None:
        self.current_kind = current_kind
        self.target_kind = target_kind
        self.orphaned_artifacts = orphaned_artifacts
        super().__init__(
            "kind migration "
            f"{current_kind or 'kindless'} -> {target_kind} orphans {_format_artifacts(orphaned_artifacts)}; "
            "re-run with --force to permanently remove them."
        )


async def migrate_todo_kind(
    todos_db: TodosDb,
    slug: str,
    *,
    target_kind: str,
    force: bool,
) -> KindMigrationResult:
    """Reroute a todo to a new kind, handling kind-specific artifacts."""
    target_kind = canonical_kind(target_kind)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise StateMutationError(f"slug {slug!r} not found in todo list")

    writer = StateWriter(raw_state)
    current_kind = canonical_kind(writer.state.kind) if writer.state.kind is not None else None
    present_artifacts = frozenset(await todos_db.list_artifacts(slug))
    orphaned_artifacts = _orphaned_artifacts(present_artifacts, target_kind)
    if orphaned_artifacts and not force:
        raise KindMigrationRequiresForce(
            current_kind=current_kind,
            target_kind=target_kind,
            orphaned_artifacts=orphaned_artifacts,
        )

    writer.state.kind = target_kind
    writer.state.lifecycle_phase = KIND_ENTRY_PHASE[target_kind]

    warnings: list[str] = []
    folded_artifact = ""
    seeded_plan_fold = _is_seeded_plan_fold(present_artifacts, orphaned_artifacts)

    input_body = ""
    implementation_plan_body = ""
    if seeded_plan_fold:
        input_body = await todos_db.read_artifact(slug, ARTIFACT_INPUT)
        implementation_plan_body = await todos_db.read_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN)

    async with todos_db._session() as session:  # pylint: disable=protected-access
        async with session.begin():
            if seeded_plan_fold:
                folded_input = _fold_plan_into_input(input_body, implementation_plan_body)
                await todos_db.write_artifact(
                    slug,
                    ARTIFACT_INPUT,
                    folded_input,
                    updated_by="todo.kind_migration",
                    session=session,
                )
                folded_artifact = ARTIFACT_IMPLEMENTATION_PLAN
                warnings.append("folded implementation-plan into input before permanently removing implementation-plan")

            for artifact_name in orphaned_artifacts:
                await todos_db.delete_artifact(slug, artifact_name, session=session)
                clear_artifact_provenance(writer, slug, artifact_name)

            await writer.commit(todos_db, slug, session=session)

    if orphaned_artifacts and not seeded_plan_fold:
        warnings.append(f"permanently removed orphaned artifacts: {_format_artifacts(orphaned_artifacts)}")

    result: KindMigrationResult = {
        "slug": slug,
        "kind": target_kind,
        "lifecycle_phase": KIND_ENTRY_PHASE[target_kind].value,
        "orphaned_artifacts": orphaned_artifacts,
        "warnings": warnings,
    }
    if folded_artifact:
        result["folded_artifact"] = folded_artifact
    return result


def _orphaned_artifacts(present_artifacts: frozenset[str], target_kind: str) -> list[str]:
    orphaned = []
    if target_kind != TODO_KIND_FEATURE:
        orphaned.extend([ARTIFACT_PRD, ARTIFACT_ARCHITECTURE])
    if target_kind != TODO_KIND_BUG:
        orphaned.append(ARTIFACT_DIAGNOSIS)
    if target_kind != TODO_KIND_TASK:
        orphaned.append(ARTIFACT_TASK_PLAN)
    if target_kind == TODO_KIND_TASK:
        orphaned.append(ARTIFACT_IMPLEMENTATION_PLAN)
    return [artifact for artifact in _ORPHAN_CHECK_ORDER if artifact in present_artifacts and artifact in orphaned]


def _is_seeded_plan_fold(present_artifacts: frozenset[str], orphaned_artifacts: list[str]) -> bool:
    seeded_plan_artifacts = frozenset({ARTIFACT_INPUT, ARTIFACT_IMPLEMENTATION_PLAN})
    return present_artifacts == seeded_plan_artifacts and (ARTIFACT_IMPLEMENTATION_PLAN in orphaned_artifacts)


def _fold_plan_into_input(input_body: str, implementation_plan_body: str) -> str:
    return f"{input_body.rstrip()}\n\n## Folded implementation plan\n\n{implementation_plan_body.strip()}\n"


def _format_artifacts(artifacts: list[str]) -> str:
    return ", ".join(artifacts)

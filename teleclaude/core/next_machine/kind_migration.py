"""Todo kind migration semantics for the update facade."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, NotRequired, TypedDict

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_TASK_PLAN,
)
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.kinds import KIND_ENTRY_PHASE, canonical_kind
from teleclaude.core.next_machine.provenance import clear_artifact_provenance
from teleclaude.core.next_machine.started_build import refuse_if_build_started
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todo_kind import TodoKind
from teleclaude.types.todos import LIFECYCLE_PHASE_STATE_KEY

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

_ITEM_VOCABULARY_PHASES = frozenset({LifecyclePhase.PREPARATION, LifecyclePhase.WAITING})
PHASE_MOVED_REFUSAL = "the phase of '{slug}' changed while its kind was being updated; repeat the update"

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

    def __init__(self, *, current_kind: str, target_kind: str, orphaned_artifacts: list[str]) -> None:
        self.current_kind = current_kind
        self.target_kind = target_kind
        self.orphaned_artifacts = orphaned_artifacts
        super().__init__(
            "kind migration "
            f"{current_kind} -> {target_kind} orphans {_format_artifacts(orphaned_artifacts)}; "
            "re-run with --force to permanently remove them."
        )


async def migrate_todo_kind(
    todos_db: WorkflowStore,
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

    refuse_if_build_started(slug, raw_state)
    writer = StateWriter(raw_state)
    current_kind = canonical_kind(writer.state.kind)
    present_artifacts = frozenset(await todos_db.list_artifacts(slug))
    orphaned_artifacts = _orphaned_artifacts(present_artifacts, target_kind)
    if orphaned_artifacts and not force:
        raise KindMigrationRequiresForce(
            current_kind=current_kind,
            target_kind=target_kind,
            orphaned_artifacts=orphaned_artifacts,
        )

    read_phase_value = writer.state.lifecycle_phase
    writer.state.kind = target_kind
    writer.state.lifecycle_phase = _phase_after_kind_change(read_phase_value, writer, target_kind)

    warnings: list[str] = []
    folded_artifact = ""
    seeded_plan_fold = _is_seeded_plan_fold(present_artifacts, orphaned_artifacts)

    input_body = ""
    implementation_plan_body = ""
    if seeded_plan_fold:
        input_body = await todos_db.read_artifact(slug, ARTIFACT_INPUT)
        implementation_plan_body = await todos_db.read_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN)

    replacement_input = None
    if seeded_plan_fold:
        replacement_input = _fold_plan_into_input(input_body, implementation_plan_body)
        folded_artifact = ARTIFACT_IMPLEMENTATION_PLAN
        warnings.append("folded implementation-plan into input before permanently removing implementation-plan")

    for artifact_name in orphaned_artifacts:
        clear_artifact_provenance(writer, slug, artifact_name)

    await todos_db.replace_item_state_and_artifacts(
        slug,
        writer.to_dict(),
        replacement_input=replacement_input,
        deleted_artifacts=orphaned_artifacts,
        precondition=partial(_refuse_if_changed, slug, read_phase_value),
    )

    if orphaned_artifacts and not seeded_plan_fold:
        warnings.append(f"permanently removed orphaned artifacts: {_format_artifacts(orphaned_artifacts)}")

    result: KindMigrationResult = {
        "slug": slug,
        "kind": target_kind,
        "lifecycle_phase": writer.state.lifecycle_phase.value,
        "orphaned_artifacts": orphaned_artifacts,
        "warnings": warnings,
    }
    if folded_artifact:
        result["folded_artifact"] = folded_artifact
    return result


def _phase_after_kind_change(read_phase_value: LifecyclePhase, writer: StateWriter, target_kind: str) -> LifecyclePhase:
    """The phase a kind change leaves the todo in.

    A todo of the item vocabulary that has not built stays where it is for a non-task kind, since it enters
    preparation whatever its kind; every other todo, and any change to the task kind, takes the target kind's entry
    phase (``local/projects/teleclaude/spec/feature/workflow/todo-management``).
    """
    prepared_record = writer.state.workflow.prepared is not None
    in_vocabulary = read_phase_value in _ITEM_VOCABULARY_PHASES or (
        read_phase_value is LifecyclePhase.PREPARED and prepared_record
    )
    if in_vocabulary and target_kind != TodoKind.TASK:
        return read_phase_value
    return KIND_ENTRY_PHASE[canonical_kind(target_kind)]


def _refuse_if_changed(slug: str, read_phase_value: LifecyclePhase, current: dict[str, StateValue] | None) -> None:
    """Under the writer lock: refuse when the build has started or the phase moved since it was read."""
    refuse_if_build_started(slug, current)
    if current is not None and current.get(LIFECYCLE_PHASE_STATE_KEY) != read_phase_value.value:
        raise StateMutationError(PHASE_MOVED_REFUSAL.format(slug=slug))


def _orphaned_artifacts(present_artifacts: frozenset[str], target_kind: str) -> list[str]:
    orphaned = []
    if target_kind != TodoKind.FEATURE:
        orphaned.extend([ARTIFACT_PRD, ARTIFACT_ARCHITECTURE])
    if target_kind != TodoKind.BUG:
        orphaned.append(ARTIFACT_DIAGNOSIS)
    if target_kind != TodoKind.TASK:
        orphaned.append(ARTIFACT_TASK_PLAN)
    if target_kind == TodoKind.TASK:
        orphaned.append(ARTIFACT_IMPLEMENTATION_PLAN)
    return [artifact for artifact in _ORPHAN_CHECK_ORDER if artifact in present_artifacts and artifact in orphaned]


def _is_seeded_plan_fold(present_artifacts: frozenset[str], orphaned_artifacts: list[str]) -> bool:
    seeded_plan_artifacts = frozenset({ARTIFACT_INPUT, ARTIFACT_IMPLEMENTATION_PLAN})
    return present_artifacts == seeded_plan_artifacts and (ARTIFACT_IMPLEMENTATION_PLAN in orphaned_artifacts)


def _fold_plan_into_input(input_body: str, implementation_plan_body: str) -> str:
    return f"{input_body.rstrip()}\n\n## Folded implementation plan\n\n{implementation_plan_body.strip()}\n"


def _format_artifacts(artifacts: list[str]) -> str:
    return ", ".join(artifacts)

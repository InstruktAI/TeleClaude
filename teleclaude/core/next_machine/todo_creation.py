"""The todo creation transaction: documentation evidence, the todo entry with its first artifact, provenance.

Every door that creates a todo calls this one transaction: the creation route that serves the CLI, and the
platform's own filing of failed required checks. A door owns its request validation and any seeding between
the two steps; the workflow service owns what a created todo is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TASK_PLAN,
    TodoStatus,
)
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.artifacts import read_artifact_write_timestamps
from teleclaude.core.next_machine.documentation_evidence import (
    DocumentationEvidenceRefused,
    require_reviewed_pending_documentation,
    snapshot_pending_carrier_blobs,
    source_commit_refs,
)
from teleclaude.core.next_machine.kinds import canonical_kind
from teleclaude.core.next_machine.lifecycle import adopt_prepare_handoff_phase
from teleclaude.core.next_machine.provenance import sync_artifact_provenance
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.workflow_store.types import DocumentationAdmission, ReviewedDocumentationSource
from teleclaude.events.envelope import EventLevel
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.producer import publish_event
from teleclaude.events.references import TodoRef
from teleclaude.events.schemas.sdlc import TodoCreated, TodoCreatedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.snippet_validation import snippet_body_digest_for
from teleclaude.types.creation_record import EntryPoint, Lineage
from teleclaude.types.todo_kind import TodoKind

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

DRIFT_TRACKED_ARTIFACT_NAMES: Final = frozenset(
    {
        ARTIFACT_INPUT,
        ARTIFACT_PRD,
        ARTIFACT_REQUIREMENTS,
        ARTIFACT_ARCHITECTURE,
        ARTIFACT_DIAGNOSIS,
        ARTIFACT_IMPLEMENTATION_PLAN,
        ARTIFACT_TASK_PLAN,
    }
)

_CREATED_EVENT_PRODUCER: Final = "api.todo.create"
_CREATED_EVENT_DOMAIN: Final = "sdlc"
_CREATION_MODE_PICKUP: Final = "pickup"
_CREATION_MODE_SILENT: Final = "silent"


@dataclass(frozen=True)
class NewTodo:
    """Everything one creation states: the todo's identity, its creation record, its first artifact and placement."""

    slug: str
    kind: TodoKind
    state: dict[str, StateValue]
    lineage: Lineage
    entry_point: EntryPoint | None
    human_involved: bool
    cwd: str
    artifact_name: str
    artifact_body: str
    session_id: str | None
    after: list[str] | None = None
    schedule: str | None = None
    group: str | None = None
    icebox: bool = False
    context: str | None = None


async def write_new_todo(todos_db: WorkflowStore, new: NewTodo) -> str:
    """Admit the todo's documentation evidence, write the entry with its first artifact, and sync provenance.

    Returns the created todo's identity.
    """
    documentation_admission = await _require_creation_documentation_evidence(
        todos_db, new.slug, new.group, icebox=new.icebox
    )
    created_identity = await todos_db.create_item_with_initial_artifact(
        new.slug,
        new.state,
        lineage=new.lineage.encode(),
        after=new.after if new.after else None,
        description=None,
        schedule=new.schedule,
        group_slug=new.group,
        status=TodoStatus.ICEBOX if new.icebox else TodoStatus.ACTIVE,
        entry_point=new.entry_point.value if new.entry_point is not None else None,
        human_involved=new.human_involved,
        context=new.context,
        cwd=new.cwd,
        artifact_name=new.artifact_name,
        artifact_body=new.artifact_body,
        updated_by=new.session_id,
        documentation_admission=documentation_admission,
    )
    if new.artifact_name in DRIFT_TRACKED_ARTIFACT_NAMES:
        await sync_artifact_provenance_state(
            todos_db,
            created_identity,
            new.artifact_name,
            repo_root=new.cwd,
            artifact_body=new.artifact_body,
            prepared_session_id=new.session_id,
        )
    return created_identity


async def announce_todo_created(
    new: NewTodo,
    *,
    identity: str,
    lifecycle_phase: str | None,
    pickup_requested: bool,
    event_id: str | None = None,
) -> None:
    """Publish the todo-created event the lifecycle router consumes; the workflow service is its one emission point.

    A door that may announce the same creation more than once states an ``event_id`` derived from the
    creation, so the repeats are one occurrence downstream.
    """
    await publish_event(
        TodoCreated(
            id=event_id,
            subject=TodoRef(identity),
            home=home_for_project_path(new.cwd),
            data=TodoCreatedData(
                slug=identity,
                kind=canonical_kind(new.kind),
                creation_mode=_CREATION_MODE_PICKUP if pickup_requested else _CREATION_MODE_SILENT,
                pickup_requested=pickup_requested,
                lifecycle_phase=lifecycle_phase,
                created_at=datetime.now(UTC).isoformat(),
                project_path=new.cwd,
                lineage=new.lineage.encode(),
                entry_point=new.entry_point.value if new.entry_point is not None else None,
                human_involved=new.human_involved,
                context=new.context,
            ),
        ),
        LegacyFacts(producer=_CREATED_EVENT_PRODUCER, level=EventLevel.WORKFLOW, domain=_CREATED_EVENT_DOMAIN),
    )


async def sync_artifact_provenance_state(
    todos_db: WorkflowStore,
    slug: str,
    artifact_name: str,
    *,
    repo_root: str,
    artifact_body: str,
    prepared_session_id: str | None,
) -> None:
    """Record a drift-tracked artifact's provenance on the todo's state, adopting the prepare handoff phase."""
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    await sync_artifact_provenance(
        todos_db,
        writer,
        slug,
        artifact_name,
        repo_root=repo_root,
        artifact_body=artifact_body,
        snippet_digest_fn=snippet_body_digest_for(repo_root),
    )
    if artifact_name == ARTIFACT_TASK_PLAN:
        artifact_write_timestamps = await read_artifact_write_timestamps(todos_db, slug)
        writer.state.lifecycle_phase = adopt_prepare_handoff_phase(
            writer.state,
            report_digests={},
            artifact_write_timestamps=artifact_write_timestamps,
            prepared_session_id=prepared_session_id,
        )
    await writer.commit(todos_db, slug)


async def _require_creation_documentation_evidence(
    todos_db: WorkflowStore,
    slug: str,
    parent_slug: str | None,
    *,
    icebox: bool,
) -> DocumentationAdmission | None:
    """Require current evidence before active admission, including first-child inputs."""
    parent_record = await todos_db.read_todo_diagnostic_record(parent_slug) if parent_slug else None
    parent_id = parent_record["id"] if parent_record is not None else None
    parent_status = TodoStatus(parent_record["status"]) if parent_record is not None else None
    has_incoming_parent = parent_record is not None and parent_record["status"] in {
        TodoStatus.ACTIVE.value,
        TodoStatus.ICEBOX.value,
    }
    if icebox:
        carrier_path_blobs = (
            snapshot_pending_carrier_blobs(todos_db.project_root, parent_slug)
            if has_incoming_parent and parent_slug is not None
            else ()
        )
        source_refs = (
            source_commit_refs(todos_db.project_root, parent_slug)
            if has_incoming_parent and parent_slug is not None
            else ()
        )
        sources: tuple[ReviewedDocumentationSource, ...] = ()
        if has_incoming_parent and parent_slug is not None:
            try:
                parked_snapshot = await require_reviewed_pending_documentation(
                    todos_db.project_root,
                    todos_db,
                    (parent_slug,),
                )
                sources = parked_snapshot.sources
            except DocumentationEvidenceRefused:
                sources = ()
        return DocumentationAdmission(
            parent_slug=parent_slug,
            parent_id=parent_id,
            parent_status=parent_status,
            sources=sources,
            carrier_path_blobs=carrier_path_blobs,
            source_commit_by_path=source_refs,
            evidence_snapshot=None,
        )
    evidence_slugs = [slug]
    if has_incoming_parent and parent_slug is not None:
        evidence_slugs.append(parent_slug)
    evidence_snapshot = await require_reviewed_pending_documentation(
        todos_db.project_root,
        todos_db,
        tuple(evidence_slugs),
    )
    sources = evidence_snapshot.sources
    parent_sources = (
        tuple(source for source in sources if source.owner_slug == parent_slug)
        if has_incoming_parent and parent_slug is not None
        else ()
    )
    return DocumentationAdmission(
        parent_slug=parent_slug,
        parent_id=parent_id,
        parent_status=parent_status,
        sources=parent_sources,
        carrier_path_blobs=tuple(
            (path, blob)
            for owner, path, blob in evidence_snapshot.carrier_blobs
            if has_incoming_parent and owner == parent_slug
        ),
        source_commit_by_path=tuple((source.carrier_path, source.source_sha) for source in parent_sources),
        evidence_snapshot=evidence_snapshot,
    )

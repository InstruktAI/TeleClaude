"""The standing an item has in the lifecycle machine's vocabulary, as `telec todo show` reports it.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (The held standing is visible): a held ``ready``
item reads as ``ready`` at its commit, held by a session since a time, with the stated reasons. The same block names an
admission, an open creative episode and the person a waiting item waits on. A todo of the task lane has no standing.
"""

from __future__ import annotations

from typing import cast

from teleclaude.core.todos_db._show import ShowPayload, TodoShowPayload, assemble_show_payload
from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_machine.reasons import reason_notes
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, Phase, WorkflowRecord


def _held_since(record: WorkflowRecord) -> str:
    """When the current claim was made: the time of the last claim in the ledger."""
    claims = [entry.at for entry in record.ledger if entry.act is Act.CLAIM]
    return claims[-1] if claims else ""


def standing_of(
    state: TodoState, ready_sha: str, ready_at: str, phase: Phase, record: WorkflowRecord
) -> dict[str, StateValue]:
    """The standing block for an item that reads ``phase``."""
    block: dict[str, StateValue] = {"phase": phase.value}
    if phase is Phase.READY:
        block["ready_at_commit"] = ready_sha
        block["ready_since"] = ready_at
        block["reasons"] = cast(
            StateValue,
            [
                {"note": note.key, "session": note.session_id, "at": note.at, "text": note.text}
                for note in reason_notes(record)
            ],
        )
    if state.active_runner:
        block["held_by"] = state.active_runner
        block["held_since"] = _held_since(record)
    if record.admitted is not None:
        block["admitted"] = {"commit": record.admitted.sha, "at": record.admitted.at}
    if record.episode is not None:
        block["creative_episode"] = cast(StateValue, record.episode.model_dump(mode="json"))
    if record.waiting is not None:
        block["waiting_on"] = record.waiting.person
    return block


async def assemble_item_show(
    store: WorkflowStore, slug: str, *, include_removed: bool = False, include_artifact_content: bool = False
) -> ShowPayload | None:
    """The show payload with the item's standing added for a live todo of the machine's vocabulary."""
    payload = await assemble_show_payload(
        store, slug, include_removed=include_removed, include_artifact_content=include_artifact_content
    )
    if payload is None or "state" not in payload:
        return payload
    raw = await store.read_state(slug)
    if raw is None:
        return payload
    state = TodoState.model_validate(raw)
    reading = read_phase(state, await resolve_lane(store, str(store.project_root), slug, raw, state))
    if reading.phase is None:
        return payload
    cast(TodoShowPayload, payload)["standing"] = standing_of(
        state, reading.ready_sha, reading.ready_at, reading.phase, state.workflow
    )
    return payload

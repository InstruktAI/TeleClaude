"""The one resolver of the facts a phase reading needs: the creative lane's answer and the integration head.

``local/projects/teleclaude/design/architecture/workflow-machine`` (a phase is read once): every consumer that reads an
item's phase resolves these facts here, or reuses the facts a caller resolved before its transaction, and hands them to
``read_phase``. No call site supplies either as a constant. The artifact revisions the creative answer depends on are read
first and travel with the facts, so a transaction fences against the observation the answer came from.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from teleclaude.constants import ARTIFACT_DESIGN_SPEC, ARTIFACT_INPUT
from teleclaude.core.next_machine.create import creative_incomplete, creative_incomplete_sync
from teleclaude.core.workflow_machine.heads import reading_head
from teleclaude.core.workflow_machine.phase_reading import LaneFacts
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState

LANE_ARTIFACTS: Final = (ARTIFACT_INPUT, ARTIFACT_DESIGN_SPEC)
"""The artifacts whose existence decides whether the creative lane has finished with an item."""


async def resolve_lane(
    store: WorkflowStore, project_root: str, item: str, raw: Mapping[str, StateValue], state: TodoState
) -> LaneFacts:
    """The lane facts of one item, read now, with the artifact revisions the creative answer rests on."""
    digests = tuple([(name, await store.artifact_digest(item, name)) for name in LANE_ARTIFACTS])
    return LaneFacts(
        creative_incomplete=await creative_incomplete(store, project_root, item, raw),
        integration_head=await reading_head(project_root, item, state),
        artifact_digests=digests,
    )


def resolve_lane_sync(
    store: WorkflowStore, project_root: str, item: str, raw: Mapping[str, StateValue], head: str
) -> LaneFacts:
    """The lane facts for a caller on a worker thread that has already read the integration head."""
    digests = tuple([(name, store.artifact_digest_sync(item, name)) for name in LANE_ARTIFACTS])
    return LaneFacts(
        creative_incomplete=creative_incomplete_sync(store, project_root, item, raw),
        integration_head=head,
        artifact_digests=digests,
    )

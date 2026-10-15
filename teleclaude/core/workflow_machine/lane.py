"""The one resolver of the facts a phase reading needs: the creative lane's answer and the integration head.

``local/projects/teleclaude/design/architecture/workflow-machine`` (a phase is read once): every consumer that reads an
item's phase resolves these facts here, or reuses the facts a caller resolved before its transaction, and hands them to
``read_phase``. No call site supplies either as a constant.
"""

from __future__ import annotations

from collections.abc import Mapping

from teleclaude.core.next_machine.create import creative_incomplete, creative_incomplete_sync
from teleclaude.core.workflow_machine.heads import reading_head
from teleclaude.core.workflow_machine.phase_reading import LaneFacts
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState


async def resolve_lane(
    store: WorkflowStore, project_root: str, item: str, raw: Mapping[str, StateValue], state: TodoState
) -> LaneFacts:
    """The lane facts of one item, read now."""
    return LaneFacts(
        creative_incomplete=await creative_incomplete(store, project_root, item, raw),
        integration_head=await reading_head(project_root, item, state),
    )


def resolve_lane_sync(
    store: WorkflowStore, project_root: str, item: str, raw: Mapping[str, StateValue], head: str
) -> LaneFacts:
    """The lane facts for a caller on a worker thread that has already read the integration head."""
    return LaneFacts(
        creative_incomplete=creative_incomplete_sync(store, project_root, item, raw), integration_head=head
    )

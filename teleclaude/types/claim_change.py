"""Recording a claim change as a pending effect of the state write that made it.

Every persistence path of an item's state applies this to the payload it is about to store. A holder
that differs from the stored one bumps the claim epoch and commits an emit-event effect with the
state, so the change is observable exactly once under one stable effect identity, whichever path
(sealed verb, dispatcher, session end) wrote it.
"""

from __future__ import annotations

from collections.abc import Mapping

from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY
from teleclaude.types.workflow_record import EffectKind, EmittedEvent, PendingEffect, WorkflowRecord

WORKFLOW_STATE_KEY = "workflow"
CLAIM_EFFECT_ID_TEMPLATE = "claim-changed:{epoch}"
PRIOR_HOLDER_PARAM = "prior_holder"
HOLDER_PARAM = "holder"
NO_HOLDER = ""
NO_ACT_KEY = ""


def stored_holder(payload: Mapping[str, StateValue]) -> str | None:
    """The claim holder a state payload records, or None when unclaimed."""
    holder = payload.get(ACTIVE_RUNNER_STATE_KEY)
    return holder if isinstance(holder, str) and holder else None


def workflow_record_of(payload: Mapping[str, StateValue]) -> WorkflowRecord:
    """The workflow record a state payload holds; an empty record when it holds none."""
    raw = payload.get(WORKFLOW_STATE_KEY)
    return WorkflowRecord.model_validate(raw if isinstance(raw, dict) else {})


def with_claim_change(payload: dict[str, StateValue], prior_holder: str | None) -> dict[str, StateValue]:
    """Return the payload with the claim change it makes committed as a pending effect.

    The payload is unchanged when the holder did not change.
    """
    holder = stored_holder(payload)
    if holder == prior_holder:
        return payload
    record = workflow_record_of(payload)
    effect = PendingEffect(
        id=CLAIM_EFFECT_ID_TEMPLATE.format(epoch=record.claim_epoch + 1),
        act_key=NO_ACT_KEY,
        kind=EffectKind.EMIT_EVENT,
        event=EmittedEvent.CLAIM_CHANGED,
        params={PRIOR_HOLDER_PARAM: prior_holder or NO_HOLDER, HOLDER_PARAM: holder or NO_HOLDER},
    )
    return {**payload, WORKFLOW_STATE_KEY: record.with_claim_change(effect).to_state()}

"""What a procedure activation reports and the delivery policy a new procedure session starts with."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import NotRequired, TypedDict, cast

from teleclaude.core.models._types import JsonDict
from teleclaude.docs_subscriptions import EventDeliveryMode

#: The root origin-metadata section a subject-bound agent's session records its binding in.
BINDING_SECTION = "procedure_binding"


class BindingField(StrEnum):
    """Persisted key names in a subject-bound agent's ``procedure_binding`` origin section."""

    PROCEDURE = "procedure"
    HOME = "home"
    SUBJECT = "subject"


class ActivationOutcome(StrEnum):
    """How an activation reached its agent: started it, woke an open one, or revived a closed one."""

    STARTED = "started"
    WOKEN = "woken"
    REVIVED = "revived"
    NOT_DELIVERED = "not_delivered"


class NotDeliveredReason(StrEnum):
    """The closed reasons an activation of a single-claim responsibility ends as ``not delivered``."""

    STALE_REQUEST = "stale request"
    NO_HOLDER = "no holder"
    SESSION_CLOSED = "session closed"


class ProcedureActivationResult(TypedDict):
    """Outcome of an activation: it started, woke or revived a procedure's agent, or delivered nothing by decision.

    A ``not delivered`` outcome names no session and carries its reason; it is a completed activation, not a failure.
    """

    session_id: str
    outcome: ActivationOutcome
    reason: NotRequired[str]


class ProcedureDeliveryInitializationField(StrEnum):
    PROCEDURE_ID = "procedure_id"
    RESPONSIBILITY_KEY = "responsibility_key"
    ACTIVATION_IDS = "activation_ids"
    EVENT_DELIVERY = "event_delivery"
    INTERRUPTIBLE = "interruptible"
    INITIAL_ENTRY_ID = "initial_entry_id"


_INVALID_PROCEDURE_DELIVERY_VALUES = "procedure delivery initialization has invalid policy values"
_INVALID_PROCEDURE_DELIVERY_IDENTITY = "procedure delivery initialization has invalid identity fields"


@dataclass(frozen=True)
class ProcedureSessionDeliveryInitialization:
    """Initial delivery policy and inbox entry committed with a new procedure session."""

    procedure_id: str
    responsibility_key: str
    activation_ids: tuple[str, ...]
    event_delivery: EventDeliveryMode
    interruptible: bool
    initial_entry_id: str

    def to_dict(self) -> JsonDict:
        return {
            ProcedureDeliveryInitializationField.PROCEDURE_ID.value: self.procedure_id,
            ProcedureDeliveryInitializationField.RESPONSIBILITY_KEY.value: self.responsibility_key,
            ProcedureDeliveryInitializationField.ACTIVATION_IDS.value: list(self.activation_ids),
            ProcedureDeliveryInitializationField.EVENT_DELIVERY.value: self.event_delivery.value,
            ProcedureDeliveryInitializationField.INTERRUPTIBLE.value: self.interruptible,
            ProcedureDeliveryInitializationField.INITIAL_ENTRY_ID.value: self.initial_entry_id,
        }

    @staticmethod
    def from_dict(data: Mapping[str, object]) -> "ProcedureSessionDeliveryInitialization":
        activation_ids = data.get(ProcedureDeliveryInitializationField.ACTIVATION_IDS)
        if (
            not isinstance(activation_ids, list)
            or not activation_ids
            or not all(isinstance(item, str) and item for item in activation_ids)
        ):
            raise ValueError(_INVALID_PROCEDURE_DELIVERY_IDENTITY)
        raw_string_fields = (
            ProcedureDeliveryInitializationField.PROCEDURE_ID,
            ProcedureDeliveryInitializationField.RESPONSIBILITY_KEY,
            ProcedureDeliveryInitializationField.INITIAL_ENTRY_ID,
        )
        if not all(isinstance(data.get(field), str) and data.get(field) for field in raw_string_fields):
            raise ValueError(_INVALID_PROCEDURE_DELIVERY_IDENTITY)
        event_delivery = data.get(ProcedureDeliveryInitializationField.EVENT_DELIVERY)
        interruptible = data.get(ProcedureDeliveryInitializationField.INTERRUPTIBLE)
        if not isinstance(event_delivery, str) or not isinstance(interruptible, bool):
            raise ValueError(_INVALID_PROCEDURE_DELIVERY_VALUES)
        return ProcedureSessionDeliveryInitialization(
            procedure_id=cast(str, data[ProcedureDeliveryInitializationField.PROCEDURE_ID]),
            responsibility_key=cast(str, data[ProcedureDeliveryInitializationField.RESPONSIBILITY_KEY]),
            activation_ids=tuple(activation_ids),
            event_delivery=EventDeliveryMode(event_delivery),
            interruptible=interruptible,
            initial_entry_id=cast(str, data[ProcedureDeliveryInitializationField.INITIAL_ENTRY_ID]),
        )

"""Shared human-facing message envelope for conversation and notification lanes.

Both the direct-conversation renderer and the operational notification lane
populate a `HumanFacingMessage` carrying a `MessageAuthor`, so identity,
provenance, and timestamp travel as one semantic contract instead of two
independently maintained identity models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

from teleclaude.helpers.agent_types import AgentName, ThinkingMode

_MISSING_DISPLAY_ERROR = "MessageAuthor requires a non-empty display identity"
_MISSING_SESSION_ID_ERROR = "MessageAuthor with kind={kind} requires a session_id"
_AGENT_MODE_SEPARATOR = "/"
_ERROR_CONTEXT_SEPARATOR = ": "
_HUMAN_ACTION_REQUIRED_ERROR = "HumanActionIntent requires non-empty {field}"
_HUMAN_ACTION_REVISION_MISMATCH_ERROR = "HumanActionIntent action_revision does not match action"


class MessageAuthorKind(StrEnum):
    """Source kind for a human-facing message's actual author."""

    HUMAN = "human"
    AGENT = "agent"
    MACHINE = "machine"


class HumanActionIntent(BaseModel):
    """Validated operational intent that crosses the event stream as a model.

    This deliberately diverges from this module's frozen dataclasses: the
    intent crosses the Redis wire and must validate its decoded shape and
    serialize its computed action revision.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str
    summary: str
    action: str
    origin_session_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_serialized_revision(cls, value: Any) -> Any:
        """Reject a transported revision that differs from the action digest."""
        if isinstance(value, dict):
            action = value.get("action")
            supplied_revision = value.get("action_revision")
            if isinstance(action, str) and supplied_revision is not None:
                expected_revision = sha256(action.encode()).hexdigest()
                if supplied_revision != expected_revision:
                    raise ValueError(_HUMAN_ACTION_REVISION_MISMATCH_ERROR)
            value = {key: item for key, item in value.items() if key != "action_revision"}
        return value

    @model_validator(mode="after")
    def _validate_required_text(self) -> HumanActionIntent:
        """Reject an action intent that cannot explain the required human action."""
        for field_name, field_value in (("topic", self.topic), ("summary", self.summary), ("action", self.action)):
            if not field_value.strip():
                raise ValueError(_HUMAN_ACTION_REQUIRED_ERROR.format(field=field_name))
        return self

    @computed_field
    @property
    def action_revision(self) -> str:
        """Return the stable revision fingerprint for the exact requested action."""
        return sha256(self.action.encode()).hexdigest()


@dataclass(frozen=True)
class MessageAuthor:
    """Resolved author identity for a human-facing message.

    Every conversation author carries the source session UUID required by the
    peer-header contract. Agent and machine authors retain their closed source
    identity instead of reducing it to display text before rendering.
    """

    kind: MessageAuthorKind
    display: str
    session_id: str | None = None
    agent_runtime: str | None = None
    thinking_mode: str | None = None
    machine_role: str | None = None

    def __post_init__(self) -> None:
        if not self.display.strip():
            raise ValueError(_ERROR_CONTEXT_SEPARATOR.join((_MISSING_DISPLAY_ERROR, str(self))))
        if self.kind is not MessageAuthorKind.HUMAN and not self.session_id:
            raise ValueError(
                _ERROR_CONTEXT_SEPARATOR.join((_MISSING_SESSION_ID_ERROR.format(kind=self.kind), str(self)))
            )
        if self.kind is MessageAuthorKind.AGENT and (not self.agent_runtime or not self.thinking_mode):
            raise ValueError("MessageAuthor AGENT requires runtime and thinking mode")
        if self.kind is MessageAuthorKind.MACHINE and not self.machine_role:
            raise ValueError("MessageAuthor MACHINE requires a machine role")
        if self.kind is MessageAuthorKind.HUMAN and any((self.agent_runtime, self.thinking_mode, self.machine_role)):
            raise ValueError("MessageAuthor HUMAN cannot carry agent or machine identity")

    @classmethod
    def for_human(cls, *, session_id: str, display_name: str) -> MessageAuthor:
        """Build the author identity for a human-authored segment."""
        return cls(kind=MessageAuthorKind.HUMAN, display=display_name, session_id=session_id)

    @classmethod
    def for_agent(
        cls,
        *,
        session_id: str,
        active_agent: str,
        thinking_mode: str | None,
    ) -> MessageAuthor:
        """Build the author identity for an agent-authored segment: `<Agent>/<mode>`."""
        runtime = AgentName.from_str(active_agent).value
        mode = ThinkingMode.from_str(thinking_mode or ThinkingMode.DEFAULT.value).value
        display = _AGENT_MODE_SEPARATOR.join((runtime.title(), mode))
        return cls(
            kind=MessageAuthorKind.AGENT,
            display=display,
            session_id=session_id,
            agent_runtime=runtime,
            thinking_mode=mode,
        )

    @classmethod
    def for_machine(cls, *, session_id: str, role_label: str) -> MessageAuthor:
        """Build the author identity for a resolved machine role (orchestrator, worker, ...)."""
        return cls(
            kind=MessageAuthorKind.MACHINE,
            display=role_label,
            session_id=session_id,
            machine_role=role_label,
        )

    @property
    def peer_token(self) -> str:
        """Return the closed author token used by the canonical peer grammar."""
        if self.kind is MessageAuthorKind.HUMAN:
            return f"human:{self.display}"
        if self.kind is MessageAuthorKind.AGENT:
            assert self.agent_runtime is not None
            assert self.thinking_mode is not None
            return f"agent:{self.agent_runtime}/{self.thinking_mode}"
        assert self.machine_role is not None
        return f"machine:{self.machine_role}"


@dataclass(frozen=True)
class HumanFacingMessage:
    """Shared semantic envelope for a human-facing TeleClaude message.

    Carries the actual author identity, the original occurrence timestamp at
    full source precision, and the human-facing body. Exact timestamps and
    internal identifiers remain in transcript and delivery metadata as
    structured provenance — this envelope is never a second copy of them.
    """

    author: MessageAuthor
    occurred_at: datetime
    body: str

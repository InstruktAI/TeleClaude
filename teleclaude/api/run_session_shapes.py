"""Run-session request shapes."""

from dataclasses import dataclass

from teleclaude.core.models import SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.types.activation_home import ActivationHome


@dataclass(frozen=True)
class RunSessionPlan:
    effective_agent: str | None
    full_command: str
    launch_intent: SessionLaunchIntent
    initiator_session_id: str | None
    origin_metadata: TerminalOriginMetadata | None
    role: str | None
    job: str | None
    company: str | None
    command: str
    working_slug: str | None
    entry_point: SessionEntryPoint
    session_id: str
    project_path: str
    subfolder: str | None
    activation_home: ActivationHome | None

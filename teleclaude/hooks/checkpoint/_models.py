"""Checkpoint data models and TypedDicts."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict

from teleclaude.core.agents import AgentName


class TranscriptObservability(TypedDict):
    """Lightweight transcript metadata used for checkpoint logging."""

    transcript_path: str
    transcript_exists: bool
    transcript_size_bytes: int


class CheckpointActionOutcome(StrEnum):
    """The terminal outcome of one action owed by a checkpoint resolution."""

    SURFACED = "surfaced"
    SATISFIED = "satisfied"
    DEFERRED = "deferred"


class CheckpointActionReason(StrEnum):
    """The reason an owed checkpoint action reached its terminal outcome."""

    ACTION_REQUIRED = "action_required"
    EVIDENCE_OBSERVED = "evidence_observed"
    OFF_MAIN_INELIGIBLE = "off_main_ineligible"


@dataclass(frozen=True)
class CheckpointOwedAction:
    """One known action selected by the effective checkpoint model."""

    action_id: str


@dataclass(frozen=True)
class CheckpointActionDecision:
    """The one terminal resolution for an action owed by a checkpoint pass."""

    action_id: str
    outcome: CheckpointActionOutcome
    reason: CheckpointActionReason


@dataclass
class CheckpointContext:
    """Session context for checkpoint heuristics."""

    agent_name: AgentName
    project_path: str = ""
    working_slug: str | None = None
    system_role: str | None = None
    session_id: str = ""
    receiver_ingress_id: str = ""


@dataclass
class CheckpointResult:
    """Output of the heuristic engine."""

    categories: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    is_all_clear: bool = False
    commit_action_required: bool = True
    on_main: bool = False
    authored_main_commit: bool = False
    post_commit_review_action_required: bool = False
    owed_actions: tuple[CheckpointOwedAction, ...] = ()
    action_decisions: tuple[CheckpointActionDecision, ...] = ()

"""Types for the memory system.

Memory stores relationship-centric observations — durable, high-signal context
about the user-agent partnership. NOT for tracking code changes or routine work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum


class ObservationType(str, Enum):
    """What kind of observation this is. Enables progressive disclosure via type filter."""

    PREFERENCE = "preference"  # User likes/dislikes, working style, communication preferences
    DECISION = "decision"  # Architectural or design choices with rationale
    DISCOVERY = "discovery"  # Something learned about a system, codebase, or domain
    GOTCHA = "gotcha"  # Pitfalls, traps, surprising behavior that bit us
    PATTERN = "pattern"  # Recurring approaches that work well
    FRICTION = "friction"  # What causes slowdowns, miscommunication, or frustration
    CONTEXT = "context"  # Project/team/domain background knowledge
    REQUEST = "request"  # Something a person asked the business for
    COMPLAINT = "complaint"  # Something a person was unhappy with
    SENTIMENT = "sentiment"  # How a person feels about the business or its offer
    COMPETITOR = "competitor"  # An alternative a person mentioned


class MemoryState(StrEnum):
    """Where a stored observation stands: kept current, retired from use, or collected as a prospect."""

    CURRENT = "current"  # A memory in use: rendered as context, searched and listed
    RETIRED = "retired"  # A memory that no longer holds: recorded, never used
    PROSPECT = "prospect"  # A business item collected for a home: raw material, never used as a memory


# The one predicate every use of memories reads through, so no read path can admit a retired
# memory or a prospect. Columns are qualified so it composes with joins and subselects.
CURRENT_MEMORY_PREDICATE = f"memory_observations.state = '{MemoryState.CURRENT.value}'"


class ExtractionStatus(StrEnum):
    """Where a released extraction stands: with its memory worker, finished, or failed with a reason."""

    READY = "ready"  # Released to a memory worker; progress has not moved past it
    COMPLETED = "completed"  # The worker declared its changes for the stretch finished; progress moved past it
    FAILED = "failed"  # The worker could not finish; the stretch is eligible again


class ObservationConcept(str, Enum):
    """Cross-cutting concept tags for richer querying."""

    HOW_IT_WORKS = "how-it-works"
    WHY_IT_EXISTS = "why-it-exists"
    PROBLEM_SOLUTION = "problem-solution"
    GOTCHA = "gotcha"
    PATTERN = "pattern"
    TRADE_OFF = "trade-off"


@dataclass
class ObservationInput:
    """Input payload for creating a memory observation."""

    text: str
    title: str | None = None
    project: str | None = None
    type: ObservationType = ObservationType.DISCOVERY
    concepts: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    identity_key: str | None = None
    subject: str | None = None
    subject_owner: str | None = None
    principal: str | None = None
    state: MemoryState = MemoryState.CURRENT
    source_session_id: str | None = None
    extraction_id: str | None = None


@dataclass
class ObservationResult:
    """Result after saving an observation."""

    id: int
    title: str
    project: str


@dataclass
class SearchResult:
    """Search result from memory observation queries."""

    id: int
    title: str | None
    subtitle: str | None
    type: str
    project: str
    narrative: str | None
    facts: list[str]
    created_at: str
    created_at_epoch: int

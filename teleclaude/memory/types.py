"""Types for the memory system.

Memory stores relationship-centric observations — durable, high-signal context
about the user-agent partnership. NOT for tracking code changes or routine work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ObservationType(str, Enum):
    """What kind of observation this is. Enables progressive disclosure via type filter."""

    PREFERENCE = "preference"  # User likes/dislikes, working style, communication preferences
    DECISION = "decision"  # Architectural or design choices with rationale
    DISCOVERY = "discovery"  # Something learned about a system, codebase, or domain
    GOTCHA = "gotcha"  # Pitfalls, traps, surprising behavior that bit us
    PATTERN = "pattern"  # Recurring approaches that work well
    FRICTION = "friction"  # What causes slowdowns, miscommunication, or frustration
    CONTEXT = "context"  # Project/team/domain background knowledge


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
    text: str
    title: str | None = None
    project: str | None = None
    type: ObservationType = ObservationType.DISCOVERY
    concepts: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)


@dataclass
class ObservationResult:
    id: int
    title: str
    project: str


@dataclass
class SearchResult:
    id: int
    title: str | None
    subtitle: str | None
    type: str
    project: str
    narrative: str | None
    facts: list[str]
    created_at: str
    created_at_epoch: int

"""Checkpoint data models and TypedDicts."""

from dataclasses import dataclass, field

from typing_extensions import TypedDict

from teleclaude.core.agents import AgentName


class TranscriptObservability(TypedDict):
    transcript_path: str
    transcript_exists: bool
    transcript_size_bytes: int


@dataclass
class CheckpointContext:
    """Session context for checkpoint heuristics."""

    agent_name: AgentName
    project_path: str = ""
    working_slug: str | None = None


@dataclass
class CheckpointResult:
    """Output of the heuristic engine."""

    categories: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    is_all_clear: bool = False

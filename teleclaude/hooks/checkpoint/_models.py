"""Checkpoint data models and TypedDicts."""

from dataclasses import dataclass, field
from typing import TypedDict

from teleclaude.core.agents import AgentName


class TranscriptObservability(TypedDict):
    """Lightweight transcript metadata used for checkpoint logging."""

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
    commit_action_required: bool = True
    on_main: bool = False
    git_head_changed_this_turn: bool = False
    post_commit_review_action_required: bool = False

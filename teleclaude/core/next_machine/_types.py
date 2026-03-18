"""Shared types, enums, dataclasses, and constants for the next-machine package.

All sub-modules import from here for shared definitions so that no circular
dependencies arise from sub-modules importing from core.py.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict

type StateScalar = str | bool | int | None
type StateValue = StateScalar | list[StateValue] | dict[str, StateValue]


class FinalizeState(TypedDict, total=False):
    status: str
    branch: str
    sha: str
    ready_at: str
    worker_session_id: str
    handed_off_at: str
    handoff_session_id: str


class PhaseName(str, Enum):
    BUILD = "build"
    REVIEW = "review"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    COMPLETE = "complete"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class ItemPhase(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class PreparePhase(str, Enum):
    """All valid prepare lifecycle phases for the state machine."""

    INPUT_ASSESSMENT = "input_assessment"
    TRIANGULATION = "triangulation"
    REQUIREMENTS_REVIEW = "requirements_review"
    TEST_SPEC_BUILD = "test_spec_build"
    TEST_SPEC_REVIEW = "test_spec_review"
    PLAN_DRAFTING = "plan_drafting"
    PLAN_REVIEW = "plan_review"
    GATE = "gate"
    GROUNDING_CHECK = "grounding_check"
    RE_GROUNDING = "re_grounding"
    PREPARED = "prepared"
    BLOCKED = "blocked"


class CreativePhase(str, Enum):
    """All valid creative lifecycle phases for the state machine."""

    CHECK_DESIGN_SPEC = "check_design_spec"
    DESIGN_DISCOVERY_REQUIRED = "design_discovery_required"
    CHECK_DS_CONFIRMATION = "check_ds_confirmation"
    DESIGN_SPEC_PENDING_CONFIRMATION = "design_spec_pending_confirmation"
    CHECK_ART = "check_art"
    ART_GENERATION_REQUIRED = "art_generation_required"
    CHECK_ART_APPROVAL = "check_art_approval"
    ART_PENDING_APPROVAL = "art_pending_approval"
    ART_ITERATION_REQUIRED = "art_iteration_required"
    CHECK_VISUALS = "check_visuals"
    VISUAL_DRAFTS_REQUIRED = "visual_drafts_required"
    CHECK_VISUAL_APPROVAL = "check_visual_approval"
    VISUALS_PENDING_APPROVAL = "visuals_pending_approval"
    VISUAL_ITERATION_REQUIRED = "visual_iteration_required"
    CREATIVE_COMPLETE = "creative_complete"
    BLOCKED = "blocked"


_PREPARE_LOOP_LIMIT = 20

DOR_READY_THRESHOLD = 8


class WorktreeScript(str, Enum):
    PREPARE = "worktree:prepare"


SCRIPTS_KEY = "scripts"
REVIEW_APPROVE_MARKER = "[x] APPROVE"
PAREN_OPEN = "("
DEFAULT_MAX_REVIEW_ROUNDS = 3
FINDING_ID_PATTERN = re.compile(r"\bR\d+-F\d+\b")
NEXT_WORK_PHASE_LOG = "NEXT_WORK_PHASE"
_PREP_STATE_VERSION = 1
_WORKTREE_PREP_STATE_REL = ".teleclaude/worktree-prep-state.json"
_PREP_INPUT_FILES = (
    "Makefile",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
)
_PREP_ROOT_INPUT_FILES = (
    "config.yml",
    "tools/worktree-prepare.sh",
)
_SINGLE_FLIGHT_GUARD = threading.Lock()

REVIEW_DIFF_NOTE = (
    "Review guard: if `git log --oneline HEAD..main` shows commits, "
    "diff must use merge-base: `git diff $(git merge-base HEAD main)..HEAD`."
)


@dataclass(frozen=True)
class WorktreePrepDecision:
    should_prepare: bool
    reason: str
    inputs_digest: str


@dataclass(frozen=True)
class EnsureWorktreeResult:
    created: bool
    prepared: bool
    prep_reason: str


@dataclass
class RoadmapEntry:
    slug: str
    group: str | None = None
    after: list[str] = field(default_factory=list)
    description: str | None = None


class RoadmapDict(TypedDict, total=False):
    slug: str
    group: str
    after: list[str]
    description: str


@dataclass
class DeliveredEntry:
    slug: str
    date: str
    commit: str | None = None
    children: list[str] | None = None


class DeliveredDict(TypedDict, total=False):
    slug: str
    date: str
    commit: str
    children: list[str]


def default_state() -> dict[str, StateValue]:
    """Return a fresh default state dict from the canonical TodoState model."""
    from teleclaude.types.todos import TodoState

    return TodoState().model_dump(exclude_none=True)  # type: ignore[return-value]

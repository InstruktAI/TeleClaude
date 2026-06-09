"""Shared types, enums, dataclasses, and constants for the next-machine package.

All sub-modules import from here for shared definitions so that no circular
dependencies arise from sub-modules importing from core.py.
"""


# Central type module participates in legacy next-machine import cycles;
# re-exports StateValue/StateScalar from teleclaude.types for backwards compatibility.

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict

from teleclaude.constants import (
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
)

# StateScalar and StateValue live in teleclaude.types.state_value so that
# low-level Pydantic models (e.g. teleclaude.types.todos) can reference them
# without importing from the next-machine feature package. Re-exported here
# for backward compatibility with the historical import path.
from teleclaude.types.state_value import StateScalar as StateScalar  # re-export
from teleclaude.types.state_value import StateValue as StateValue  # re-export
from teleclaude.types.todos import TodoState


class FinalizeState(TypedDict, total=False):
    """Durable handoff metadata stored for finalize processing."""

    status: str
    branch: str
    sha: str
    ready_at: str


class PhaseName(str, Enum):
    """Top-level machine phases stored in state.yaml."""

    BUILD = "build"
    REVIEW = "review"


class PhaseStatus(str, Enum):
    """Allowed statuses for top-level build and review phases."""

    PENDING = "pending"
    STARTED = "started"
    COMPLETE = "complete"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class ItemPhase(str, Enum):
    """Lifecycle phases for a todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class PreparePhase(str, Enum):
    """All valid prepare lifecycle phases for the state machine."""

    DRAFT = "draft"
    PRD_DRAFTING = "prd_drafting"
    PRD_HUMAN_APPROVAL = "prd_human_approval"
    ARCHITECTURE_DRAFTING = "architecture_drafting"
    ARCHITECTURE_REVIEW = "architecture_review"
    DIAGNOSE = "diagnose"
    PLAN_DRAFTING = "plan_drafting"
    PLAN_REVIEW = "plan_review"
    PREPARED = "prepared"
    BLOCKED = "blocked"


class WorkPhase(str, Enum):
    """Canonical work-lane lifecycle phases."""

    BUILD_STARTED = "build_started"
    BUILD_COMPLETE = "build_complete"
    REVIEW_CHANGES_REQUESTED = "review_changes_requested"
    REVIEW_APPROVED = "review_approved"
    FINALIZE_READY = "finalize_ready"


WORK_PHASE_ORDER: list[str] = [phase.value for phase in WorkPhase]


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
_WORK_LOOP_LIMIT = 10

DOR_READY_THRESHOLD = 8


class WorktreeScript(str, Enum):
    """Named repo scripts that can prepare a worktree."""

    PREPARE = "worktree:prepare"


SCRIPTS_KEY = "scripts"
PAREN_OPEN = "("
DEFAULT_MAX_REVIEW_ROUNDS = 3
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
ARTIFACT_UPSTREAMS: dict[str, tuple[str, ...]] = {
    STATE_KEY_PRD: (STATE_KEY_INPUT,),
    STATE_KEY_ARCHITECTURE: (STATE_KEY_PRD,),
    STATE_KEY_DIAGNOSIS: (STATE_KEY_INPUT,),
    STATE_KEY_IMPLEMENTATION_PLAN: (STATE_KEY_PRD, STATE_KEY_ARCHITECTURE, STATE_KEY_DIAGNOSIS),
}

REVIEW_DIFF_NOTE = (
    "Review guard: if `git log --oneline HEAD..main` shows commits, "
    "diff must use merge-base: `git diff $(git merge-base HEAD main)..HEAD`."
)


@dataclass(frozen=True)
class WorktreePrepDecision:
    """Whether worktree preparation should run for the current inputs."""

    should_prepare: bool
    reason: str
    inputs_digest: str


@dataclass(frozen=True)
class EnsureWorktreeResult:
    """Outcome of ensuring a worktree exists and is prepared."""

    created: bool
    prepared: bool
    prep_reason: str


def default_state() -> dict[str, StateValue]:
    """Return a fresh default state dict from the canonical TodoState model."""
    return TodoState().model_dump(exclude_none=True)

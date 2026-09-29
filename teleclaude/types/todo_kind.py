"""Canonical TodoKind vocabulary — single source of truth for all todo kind values.

A kind is the work-unit's entry point into the lifecycle. There are exactly four:
  feature → enters at intake (needs a PRD)
  change  → enters at plan (a known change to existing code; no PRD; intent is the input artifact)
  bug     → enters at diagnose (a defect; no PRD; verify the diagnosis first, then draft a plan)
  task    → non-SDLC, created silent, tracked by a task-plan artifact, side-effect
            only — never touches the repo (sdlc/spec/todo-kind-task)

Orthogonal creation inputs (never declared as a kind):
  --plan <content> supplies a finished implementation-plan; the orchestrator fast-forwards entry to build.
  --silent creates without dispatch; freeze/icebox parks an item later.

The kind → entry-phase routing table lives in ``teleclaude.core.next_machine.kinds`` (KIND_ENTRY_PHASE).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class TodoKind(StrEnum):
    """Closed vocabulary of todo lifecycle entry kinds."""

    FEATURE = "feature"
    CHANGE = "change"
    BUG = "bug"
    TASK = "task"


TODO_KIND_FEATURE: Final[TodoKind] = TodoKind.FEATURE
TODO_KIND_CHANGE: Final[TodoKind] = TodoKind.CHANGE
TODO_KIND_BUG: Final[TodoKind] = TodoKind.BUG
TODO_KIND_TASK: Final[TodoKind] = TodoKind.TASK

# Backfill value the state upcycle assigns to a legacy row with no kind. The
# upcycle also holds the row until an operator sets its real kind and releases it.
# Creation boundaries require an explicit kind; this is never a runtime fallback.
TODO_KIND_DEFAULT: Final[TodoKind] = TodoKind.FEATURE

# API boundary alias for the closed kind type.
TodoDumpKind = TodoKind

# All valid values accepted by the CLI --kind flag and the API dump endpoint.
TODO_KIND_CHOICES: Final[tuple[TodoKind, ...]] = (
    TODO_KIND_FEATURE,
    TODO_KIND_CHANGE,
    TODO_KIND_BUG,
    TODO_KIND_TASK,
)
TODO_KIND_USAGE: Final[str] = "|".join(TODO_KIND_CHOICES)
ALL_DUMP_KINDS: frozenset[TodoKind] = frozenset(TODO_KIND_CHOICES)

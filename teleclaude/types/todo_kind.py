"""Canonical TodoKind vocabulary — single source of truth for all todo kind values.

A kind is the work-unit's entry point into the lifecycle. There are exactly four:
  feature → enters at intake (needs a PRD)
  change  → enters at plan (a known change to existing code; no PRD; intent is the input artifact)
  bug     → enters at diagnose (a defect; no PRD; verify the diagnosis first, then draft a plan)
  task    → non-SDLC, created silent, tracked by a task-plan artifact, side-effect
            only — never touches the repo (software-development/spec/todo-kind-task)

Orthogonal creation inputs (never declared as a kind):
  --plan <content> supplies a finished implementation-plan; the orchestrator fast-forwards entry to build.
  --silent creates without dispatch; freeze/icebox parks an item later.

The kind → entry-phase routing table lives in ``teleclaude.core.next_machine.kinds`` (KIND_ENTRY_PHASE).
"""

from __future__ import annotations

from typing import Final, Literal

TODO_KIND_FEATURE: Final = "feature"
TODO_KIND_CHANGE: Final = "change"
TODO_KIND_BUG: Final = "bug"
TODO_KIND_TASK: Final = "task"

# Backfill value the state upcycle assigns to legacy rows that predate explicit
# kind selection. Never a runtime fallback — every input boundary requires an
# explicit kind, and the read boundary hard-fails on a missing kind.
TODO_KIND_DEFAULT: Final = TODO_KIND_FEATURE

# Literal type alias for static type checking at API boundaries.
TodoDumpKind = Literal["feature", "change", "bug", "task"]

# All valid values accepted by the CLI --kind flag and the API dump endpoint.
TODO_KIND_CHOICES: Final[tuple[TodoDumpKind, ...]] = (
    TODO_KIND_FEATURE,
    TODO_KIND_CHANGE,
    TODO_KIND_BUG,
    TODO_KIND_TASK,
)
TODO_KIND_USAGE: Final[str] = "|".join(TODO_KIND_CHOICES)
ALL_DUMP_KINDS: frozenset[str] = frozenset(TODO_KIND_CHOICES)

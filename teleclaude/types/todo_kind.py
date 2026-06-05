"""Canonical TodoKind vocabulary — single source of truth for all todo kind values.

A kind is the work-unit's entry point into the lifecycle. There are exactly three:
  feature → enters at intake (needs a PRD)
  change  → enters at plan (a known change to existing code; no PRD; intent is the input artifact)
  bug     → enters at fix (a defect; no PRD and no upfront plan)

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

# Backfill value the state upcycle assigns to legacy rows that predate explicit
# kind selection. Never a runtime fallback — every input boundary requires an
# explicit kind, and the read boundary hard-fails on a missing kind.
TODO_KIND_DEFAULT: Final = TODO_KIND_FEATURE

# All valid values accepted by the CLI --kind flag and the API dump endpoint.
ALL_DUMP_KINDS: frozenset[str] = frozenset({TODO_KIND_FEATURE, TODO_KIND_CHANGE, TODO_KIND_BUG})

# Literal type alias for static type checking at API boundaries.
TodoDumpKind = Literal["feature", "change", "bug"]

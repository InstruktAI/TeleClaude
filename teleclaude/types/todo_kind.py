"""Canonical TodoKind vocabulary — single source of truth for all todo kind values.

Every layer that needs to branch on or validate ``kind`` imports from here.
No layer defines its own kind vocabulary; divergent definitions must fail lint.

Routing semantics (enforced by the lifecycle router):
  Content kinds → prepare lane: feature, refactor, migration, todo
  Bug lane:                       bug
  Pre-prepared, skip to work:     prepped
  Parked, no lifecycle:           draft
"""

from __future__ import annotations

from typing import Final, Literal

TODO_KIND_FEATURE: Final = "feature"
TODO_KIND_REFACTOR: Final = "refactor"
TODO_KIND_MIGRATION: Final = "migration"
TODO_KIND_BUG: Final = "bug"
TODO_KIND_TODO: Final = "todo"
TODO_KIND_PREPPED: Final = "prepped"
TODO_KIND_DRAFT: Final = "draft"

# Default kind for state deserialization of rows predating explicit kind selection.
TODO_KIND_DEFAULT: Final = TODO_KIND_TODO

# Kinds that route to the prepare lane.
PREPARE_LANE_KINDS: frozenset[str] = frozenset(
    {TODO_KIND_FEATURE, TODO_KIND_REFACTOR, TODO_KIND_MIGRATION, TODO_KIND_TODO}
)

# All valid values accepted by the CLI --kind flag and the API dump endpoint.
ALL_DUMP_KINDS: frozenset[str] = frozenset(
    {
        TODO_KIND_FEATURE,
        TODO_KIND_REFACTOR,
        TODO_KIND_MIGRATION,
        TODO_KIND_BUG,
        TODO_KIND_TODO,
        TODO_KIND_PREPPED,
        TODO_KIND_DRAFT,
    }
)

# Literal type alias for static type checking at API boundaries.
TodoDumpKind = Literal[
    "feature",
    "refactor",
    "migration",
    "bug",
    "todo",
    "prepped",
    "draft",
]

"""Todo kind groupings shared by lifecycle state machines."""

from __future__ import annotations

KIND_BUG = "bug"
KIND_DRAFT = "draft"
KIND_FEATURE = "feature"
KIND_MIGRATION = "migration"
KIND_PREPPED = "prepped"
KIND_REFACTOR = "refactor"
KIND_TODO = "todo"

FEATURE_PREPARE_KINDS = frozenset({"", KIND_TODO, KIND_FEATURE, KIND_DRAFT})
PLAN_ONLY_PREPARE_KINDS = frozenset({KIND_REFACTOR, KIND_MIGRATION})
FAST_TRACK_PREPARED_KINDS = frozenset({KIND_BUG, KIND_PREPPED})
PLAN_WITHOUT_INTENT_UPSTREAM_KINDS = PLAN_ONLY_PREPARE_KINDS | frozenset({KIND_PREPPED})

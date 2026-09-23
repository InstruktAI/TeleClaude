"""Qualify stored session command identities to their domain-partitioned values.

The global command corpus is now partitioned by domain
(`agents/global/commands/<domain>/`), and every `SlashCommand` member's value
carries that domain as its first segment (see `teleclaude.constants`). A
session row recorded before this cutover carries the old bare value in its
`command` column; live lifecycle, creative, job, and onboarding lookups key
this column against the qualified `SlashCommand` values, so an unmigrated row
would silently stop matching. This is a one-way forward migration of owned
data: the old bare values disappear at this boundary and no compatibility
branch is added — see `software-development/policy/backward-compatibility-hygiene`.
"""

from __future__ import annotations

import aiosqlite

# old bare value -> new domain-qualified value, one entry per SlashCommand
# member the corpus partition renamed. Values are captured here as literals
# because the old ones no longer exist anywhere else in the codebase.
_COMMAND_RENAMES: dict[str, str] = {
    "analyze-todo-input": "software-development/analyze-todo-input",
    "next-build": "software-development/next-build",
    "next-review-build": "software-development/next-review-build",
    "next-review-prd": "software-development/next-review-prd",
    "next-review-plan": "software-development/next-review-plan",
    "next-review-architecture": "software-development/next-review-architecture",
    "next-review-commits": "software-development/next-review-commits",
    "next-finalize": "software-development/next-finalize",
    "next-prepare-intake": "software-development/next-prepare-intake",
    "next-prepare-architecture": "software-development/next-prepare-architecture",
    "next-prepare-diagnose": "software-development/next-prepare-diagnose",
    "next-prepare-plan": "software-development/next-prepare-plan",
    "next-prepare-task": "software-development/next-prepare-task",
    "next-drift-analyze": "software-development/next-drift-analyze",
    "next-prepare": "software-development/next-prepare",
    "next-work": "software-development/next-work",
    "next-run-task": "software-development/next-run-task",
    "next-integrate": "software-development/next-integrate",
    "next-coordinate": "software-development/next-coordinate",
    "next-create": "creative/next-create",
    "next-create-art": "creative/next-create-art",
    "next-create-html": "creative/next-create-html",
    "next-defer": "software-development/next-defer",
    "next-assist": "software-development/next-assist",
    "next-run-job": "general/next-run-job",
}

_UPDATE_COMMAND_SQL = "UPDATE sessions SET command = ? WHERE command = ?"


async def up(db: aiosqlite.Connection) -> None:
    """Rewrite recognized stored bare session command identities to their qualified values."""
    for old_value, new_value in _COMMAND_RENAMES.items():
        await db.execute(_UPDATE_COMMAND_SQL, (new_value, old_value))
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""

"""Rename stored session command and job identities to the `sdlc` domain and unprefixed command names.

The `software-development` domain is now `sdlc`, and global commands no longer
carry a `next-` prefix (see `teleclaude.constants.SlashCommand`). Lifecycle,
creative, job and onboarding lookups key `sessions.command` against the current
`SlashCommand` values, and job lookups key `sessions.job` against procedure
snippet ids, so an unmigrated row would silently stop matching. This is a
one-way forward migration of owned data with no compatibility branch — see
`sdlc/policy/backward-compatibility-hygiene`. Old values are captured as
literals because they no longer exist anywhere else in the codebase.
"""

from __future__ import annotations

import aiosqlite

# old stored value -> current value, one entry per command a session may have recorded.
_COMMAND_RENAMES: dict[str, str] = {
    "software-development/analyze-todo-input": "sdlc/analyze-todo-input",
    "software-development/next-assist": "sdlc/assist",
    "software-development/next-build": "sdlc/build",
    "software-development/next-coordinate": "sdlc/coordinate",
    "software-development/next-defer": "sdlc/defer",
    "software-development/next-drift-analyze": "sdlc/drift-analyze",
    "software-development/next-finalize": "sdlc/finalize",
    "software-development/next-integrate": "sdlc/integrate",
    "software-development/next-prepare": "sdlc/prepare",
    "software-development/next-prepare-architecture": "sdlc/prepare-architecture",
    "software-development/next-prepare-diagnose": "sdlc/prepare-diagnose",
    "software-development/next-prepare-intake": "sdlc/prepare-intake",
    "software-development/next-prepare-plan": "sdlc/prepare-plan",
    "software-development/next-prepare-task": "sdlc/prepare-task",
    "software-development/next-research": "sdlc/research",
    "software-development/next-review-architecture": "sdlc/review-architecture",
    "software-development/next-review-build": "sdlc/review-build",
    "software-development/next-review-commits": "sdlc/review-commits",
    "software-development/next-review-plan": "sdlc/review-plan",
    "software-development/next-review-prd": "sdlc/review-prd",
    "software-development/next-run-task": "sdlc/run-task",
    "software-development/next-work": "sdlc/work",
    "software-development/projects-analyze": "sdlc/projects-analyze",
    "software-development/projects-assess-config": "sdlc/projects-assess-config",
    "creative/next-create": "creative/create",
    "creative/next-create-art": "creative/create-art",
    "creative/next-create-html": "creative/create-html",
    "general/next-run-job": "general/run-job",
    # Bare values recorded before domain qualification whose commands 085 did not cover.
    "next-research": "sdlc/research",
    "projects-analyze": "sdlc/projects-analyze",
    "projects-assess-config": "sdlc/projects-assess-config",
    "projects-onboard": "general/projects-onboard",
    "companies-analyze": "general/companies-analyze",
}
_OLD_DOMAIN_PREFIX = "software-development/"
_NEW_DOMAIN_PREFIX = "sdlc/"

_UPDATE_COMMAND_SQL = "UPDATE sessions SET command = ? WHERE command = ?"
_UPDATE_JOB_SQL = "UPDATE sessions SET job = ? || substr(job, ?) WHERE substr(job, 1, ?) = ?"


async def up(db: aiosqlite.Connection) -> None:
    """Rewrite stored session command and job identities to their current values."""
    for old_value, new_value in _COMMAND_RENAMES.items():
        await db.execute(_UPDATE_COMMAND_SQL, (new_value, old_value))
    prefix_length = len(_OLD_DOMAIN_PREFIX)
    await db.execute(_UPDATE_JOB_SQL, (_NEW_DOMAIN_PREFIX, prefix_length + 1, prefix_length, _OLD_DOMAIN_PREFIX))
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""

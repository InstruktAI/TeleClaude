---
id: 'project/policy/single-database'
type: 'policy'
scope: 'project'
description: 'Database boundaries follow domain boundaries. Each domain owns its storage.'
---

# Database Boundaries — Policy

## Rules

- Database files follow domain boundaries, not a single-file mandate.
- **Daemon operational database** (`teleclaude.db`): sessions, hooks, memory, agent
  metadata — daemon plumbing with shared access patterns.
- **Event platform database** (`events.db`): notification projections, trust state,
  mesh peer data — event domain storage with its own lifecycle.
- Each domain owns its database file. Tables within a domain belong together.
- Git worktrees use isolated database files for test isolation and must not touch
  production state.
- The daemon must not create ad-hoc database files outside recognized domain boundaries.

## Rationale

- Domain separation reflects real architectural boundaries. Cramming unrelated data
  into one file because "fewer files = simpler" ignores access patterns, lifecycle
  differences, and operational concerns.
- The event platform naturally separated because it IS a different domain.

## Scope

- Applies to the running daemon in the main repository.

## Enforcement

- Each recognized database file serves one domain. Stray `.db` files outside
  recognized domains are treated as bugs.
- New domains justify new database files; new tables within a domain go in the
  existing domain database.

## Exceptions

- None.

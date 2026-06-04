---
description: 'Database boundaries follow domain boundaries. Each domain owns its storage.'
id: 'project/policy/single-database'
scope: 'project'
type: 'policy'
visibility: 'public'
status: 'actual'
---

# Database Boundaries — Policy

## Rules

- Database files follow domain boundaries, not a single-file mandate.
- All databases live under `~/.teleclaude/`.
- **Daemon operational database** (`~/.teleclaude/teleclaude.db`): sessions, hooks,
  memory, agent metadata — daemon plumbing with shared access patterns.
- **Mirror database** (`~/.teleclaude/mirrors.db`): session transcript mirrors and
  FTS search — separate domain with large payloads and independent lifecycle.
- **Event platform database** (`~/.teleclaude/events.db`): notification projections,
  trust state, mesh peer data — event domain storage with its own lifecycle.
- **Hook outbox database** (`~/.teleclaude/hook_outbox.db`): hook receiver ingress
  queue — operational hook delivery state owned by daemon maintenance.
- Each domain owns its database file. Tables within a domain belong together.
- Runtime maintenance may prune or compact operational domains
  (`teleclaude.db`, `hook_outbox.db`, `events.db`) according to retention policy,
  but must not prune durable/history domains such as `mirrors.db`, memory data,
  todo databases, or project artifact stores.
- **Sanctioned exception — retention finalization of explicitly-removed todo
  rows.** Runtime maintenance MAY hard-purge todo-database rows that an operator
  or agent has _explicitly removed_ (soft-deleted: marked `removed` with a
  `removed_at` tombstone) once they are older than the fixed recovery-retention
  window. This is the finalization of an already-explicit removal after a
  recovery grace period — not blind pruning of live durable work. The
  prohibition above still holds for all _live_ (non-removed) todo data: routine
  maintenance must never prune a todo that has not been explicitly removed.
- Git worktrees use isolated database files for test isolation and must not touch
  production state.
- The daemon must not create ad-hoc database files outside recognized domain boundaries.

## Rationale

- Domain separation reflects real architectural boundaries. Cramming unrelated data
  into one file because "fewer files = simpler" ignores access patterns, lifecycle
  differences, and operational concerns.
- The event platform naturally separated because it IS a different domain.
- The retention-finalization carve-out reduces data-loss risk rather than
  increasing it: it replaces an immediate irreversible destroy with a
  recoverable grace period followed by automatic cleanup, mirroring the
  closed-session soft-delete + retention model the platform already runs.

## Scope

- Applies to the running daemon in the main repository.

## Enforcement

- Each recognized database file serves one domain. Stray `.db` files outside
  recognized domains are treated as bugs.
- New domains justify new database files; new tables within a domain go in the
  existing domain database.

## Exceptions

- Retention finalization of explicitly-removed (soft-deleted) todo rows after
  the fixed recovery-retention window, as specified in Rules. No other
  exception.

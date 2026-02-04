---
id: project/baseline/policy/single-database
type: policy
scope: project
description: Guaranteed single database file usage for the daemon to prevent data
  fragmentation.
---

# Single Database — Policy

## Rules

- The daemon uses a single SQLite file: `teleclaude.db` at the project root.
- The database path is `${WORKING_DIR}/teleclaude.db` in `config.yml`.
- The daemon must never create, copy, or duplicate the production database file.
- Extra `.db` files in the main repo are treated as bugs and removed.
- Git worktrees use isolated `teleclaude.db` files for test isolation and must not touch production state.

## Rationale

- Prevents state fragmentation and avoids split-brain behavior.

## Scope

- Applies to the running daemon in the main repository.

## Enforcement

- Verify `teleclaude.db` path is the only active database in production.
- Delete any additional `.db` files found outside worktrees.

## Exceptions

- None in production; only isolated worktrees may use separate databases.

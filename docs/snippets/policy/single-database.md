---
id: policy/single-database
type: policy
scope: project
description: Guaranteed single database file usage for the daemon to prevent data fragmentation.
---

# Single Database Policy

## Purpose
Ensures that the running TeleClaude daemon always uses a single source of truth for its state, preventing data fragmentation and synchronization issues.

## Rules
1. **Canonical Path**: The daemon MUST only use `teleclaude.db` located in the project root.
2. **Configuration**: The database path is defined in `config.yml` as `${WORKING_DIR}/teleclaude.db`.
3. **No Duplicates**: The daemon MUST NEVER create, copy, or duplicate the production database file.
4. **Cleanup**: Any additional `.db` files found in the main repository (outside of worktrees) MUST be deleted immediately as they indicate a bug.

## Exceptions
- **Git Worktrees**: Worktrees use isolated `teleclaude.db` files for test isolation and development sandboxing. This is intentional and these databases must never touch the production database.
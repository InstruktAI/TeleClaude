# Implementation Plan: Postgres Migration

## Overview

Replace SQLite with Postgres as the only database backend. Add a migration script to import current data from `teleclaude.db` into Postgres, update configuration, and restart the daemon.

## Decisions

- **No rollback or fallback** support.
- **Single Postgres database**: `teleklaude`.
- **Breaking change**: SQLite is no longer supported after cutover.

## Phase 1: Postgres Backend

1. Add Postgres driver dependency (e.g., `asyncpg` or `SQLAlchemy[asyncio]`).
2. Introduce a DB backend interface and a Postgres implementation.
3. Map SQLite schema to Postgres types:
   - `INTEGER PRIMARY KEY` -> `BIGSERIAL` or `UUID` (match current usage)
   - `TEXT` -> `TEXT`
   - `BLOB` -> `BYTEA`
   - `JSON` -> `JSONB`
4. Ensure indexes and unique constraints match current behavior.

## Phase 2: Migration Tool

1. Build `scripts/migrate_sqlite_to_postgres.py`.
2. Read from `teleclaude.db` and bulk-insert into Postgres in dependency order.
3. Include:
   - `--dry-run` (connectivity and schema checks)
   - `--verify` (row counts + basic integrity checks)
   - `--resume` (skip tables already migrated)
4. Data order (adjust based on actual schema):
   - `computers`
   - `sessions`
   - `session_logs` / `transcripts` / `messages`
   - `pending_deletions`
   - `hook_outbox`
   - any remaining tables

## Phase 3: Cutover

1. Stop new writes briefly (announce maintenance window internally).
2. Run migration tool once.
3. Update config to Postgres:
   - `config.yml` uses Postgres DSN from `.env`.
4. Restart daemon with `make restart`.
5. Verify with `make status` and check logs for DB errors.

## Validation

- Confirm daemon starts cleanly.
- Run a short AI-to-AI session and confirm listener feedback arrives.
- Verify no `database is locked` errors in logs.

## Deliverables

- Postgres backend in codebase.
- Migration script in `scripts/`.
- Updated config/ENV usage.
- Runbook steps documented in `docs/` or `README.md` (short section).

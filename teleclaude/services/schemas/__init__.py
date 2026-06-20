"""Postgres schema definitions — one SQL file per domain pillar.

Schema files define the target state for each domain. They are used
by Alembic migrations to create and evolve the database structure.

Pillars:
    events.sql   — event channel outbox tables, subscriber cursors, NOTIFY triggers
    work.sql     — todos, artifacts, todo (domain-discriminated)
    runtime.sql  — ephemeral session state, tokens, operations
    ledger.sql   — permanent session archive, blocks, projections
    identity.sql — people, credentials, roles
    context.sql  — snippet reflections, memory observations
"""

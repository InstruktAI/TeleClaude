---
description: 'How the daemon database reaches the current schema: schema.sql is the end state, fresh databases stamp their migrations, existing databases replay them before schema.sql adds the rest, and every migration is idempotent.'
visibility: 'internal'
---

# Schema And Migrations — Policy

## Rules

<!-- planned:teleclaude-db-split -->

- **Each daemon store owns its schema file and its migration ledger.** The core
  database and every store split from it each keep their own `schema.sql`,
  their own numbered migrations and their own `schema_migrations` ledger inside
  their own file. The rules below apply to each store against its own schema
  file and ledger.
- **A table that moves to another store is moved by a migration of the store it
  leaves.** That migration creates the table in the target store at the shape the
  source store left it, copies the rows the move carries, and drops the table
  from the source. The target store's schema file declares the table, and its
  own migrations then meet the shape they were written against.

<!-- /planned:teleclaude-db-split -->

- **`schema.sql` is the authoritative current schema.** It is the complete end
  state of the daemon database, not a historical starting point. Every table,
  column, and index the running system expects is declared there.
- **A database with no tables is created from `schema.sql`, and its migrations are
  recorded as applied without being run.** A database born under the current
  schema has nothing to upgrade; replaying history over it is redundant where the
  result is already present and fatal where the schema has since been reshaped
  past the shape a migration was written against.
- **A database that already holds tables runs its pending migrations first, then
  executes `schema.sql`.** Each pending migration meets the shape its predecessors
  left, however many releases the database skipped; `schema.sql`, written with
  `CREATE ... IF NOT EXISTS`, then only adds what the migration history does not
  create.
- **A migration is written against the shape its predecessors leave.** That shape
  is its contract; `schema.sql` moves forward with the code and is never the input
  a migration converges from.
- **Every migration is idempotent.** `CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, and an `ALTER TABLE ... ADD COLUMN` guarded by a
  `pragma_table_info` check for the column. A database can already hold a
  migration's result — created by an earlier `schema.sql` run before the
  migration existed — and the migration converges on it without failing.
- **Adding a table or column requires both `schema.sql` and a migration.** Either
  alone is a defect: `schema.sql` alone leaves every existing database without the
  change, and a migration alone leaves every fresh database without it, because a
  fresh database stamps rather than runs.
- **A migration whose result is fully expressed by an earlier migration is deleted,
  not left in place.** Two migrations that both add the same column collide on the
  second, and the collision surfaces only on the databases that reach it.

## Rationale

Two paths reach the same schema and only one of them runs migration bodies. Fresh
databases take the whole shape from `schema.sql` in one step; existing databases
close the gap by replaying their pending history, then take whatever `schema.sql`
still adds.

Replaying history before applying the end state is what makes a skipped release
safe. `schema.sql` presents tables in their newest shape; a migration that reshapes
a table from an older shape cannot recognise that it has been overtaken, so running
`schema.sql` first hands it an input it was never written for and startup raises.
Replayed in order, each migration reads exactly the shape it was authored against.

The idempotency rule covers what ordering cannot: a database already carries
whatever earlier startups created, so a migration can still find its own result
present.

<!-- planned:teleclaude-db-split -->

A store is its own write-isolation unit (`sdlc/policy/state-storage`), so its
schema history travels with its file: a ledger kept in another file could record
a migration as applied to a store that never received it. Moving a table through
the source store's migration keeps the replay guarantee across the move — the
table arrives in its new store at the shape the source history produced, never at
a newer shape the copied rows were not written for.

<!-- /planned:teleclaude-db-split -->

Startup is non-retryable, so the blast radius is the whole daemon rather than one
feature. Hook receivers compound it — they execute from the checkout per event and
do not wait for the daemon, so between a merge and the next restart they run new
code against a database whose migrations have not applied.

## Scope

<!-- planned-change:teleclaude-db-split -->

Every database this repository owns and every migration under
`teleclaude/core/migrations/`.

<!-- change:teleclaude-db-split -->

Every database this repository owns and every migration of each of its stores.

<!-- /planned-change:teleclaude-db-split -->

## Enforcement

- A migration using bare `CREATE TABLE`, bare `CREATE INDEX`, or an unguarded
  `ALTER TABLE ... ADD COLUMN` is a defect, whether or not it currently passes.
- A table or column present in `schema.sql` with no migration, or in a migration
  with no `schema.sql` declaration, is a defect.

<!-- planned-change:teleclaude-db-split -->

- Reviewers check both paths for any change touching `schema.sql` or
  `teleclaude/core/migrations/`: would this apply cleanly to a database that
  already has its result, and to one at its predecessor's shape; and would a
  database created purely from `schema.sql` be complete without it.

<!-- change:teleclaude-db-split -->

- Reviewers check both paths for any change touching a store's schema file or
  migrations: would this apply cleanly to a database that already has its
  result, and to one at its predecessor's shape; and would a database created
  purely from that store's schema file be complete without it.

<!-- /planned-change:teleclaude-db-split -->

## Exceptions

- None. A migration that cannot be made idempotent is a migration whose target
  shape is wrong.

## See Also

- ~/.teleclaude/docs/sdlc/policy/state-storage.md — whether state needs a database, and which database file it belongs in.

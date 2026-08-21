---
description: 'How the daemon database reaches the current schema: schema.sql is the end state, fresh databases stamp their migrations, existing databases replay them, and every migration is therefore idempotent.'
visibility: 'internal'
---

# Schema And Migrations — Policy

## Rules

- **`schema.sql` is the authoritative current schema.** It is the complete end
  state of the daemon database, not a historical starting point. Every table,
  column, and index the running system expects is declared there.
- **A database with no tables is created from `schema.sql`, and its migrations are
  recorded as applied without being run.** A database born under the current
  schema has nothing to upgrade; replaying history over it is redundant where the
  result is already present and fatal where the schema has since been reshaped
  past the shape a migration was written against.
- **A database that already holds tables executes `schema.sql` first, then runs its
  pending migrations.** `schema.sql` is written with `CREATE ... IF NOT EXISTS`, so
  this is additive — but it means **a migration can find its own result already
  present** before it runs.
- **Every migration is therefore idempotent.** `CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, and an `ALTER TABLE ... ADD COLUMN` guarded by a
  `pragma_table_info` check for the column. A migration converges on the current
  shape whether or not `schema.sql` reached it first.
- **A migration never assumes the shape `schema.sql` had when it was authored.**
  `schema.sql` moves forward with the code; the migration must still converge
  against the shape it finds.
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
take whatever `schema.sql` adds and then close the remaining gap by migration.
Because `schema.sql` runs first on both paths, the migration is the party that
must tolerate finding the work done — never the reverse.

The idempotency rule is what makes the split safe rather than merely convenient.
Without it, every forward edit to `schema.sql` arms a failure on the existing-
database path: the table appears at bootstrap, the migration then asserts it into
a schema that already has it, and startup raises.

Startup is non-retryable, so the blast radius is the whole daemon rather than one
feature. Hook receivers compound it — they execute from the checkout per event and
do not wait for the daemon, so between a merge and the next restart they run new
code against a database whose migrations have not applied.

## Scope

Every database this repository owns and every migration under
`teleclaude/core/migrations/`.

## Enforcement

- A migration using bare `CREATE TABLE`, bare `CREATE INDEX`, or an unguarded
  `ALTER TABLE ... ADD COLUMN` is a defect, whether or not it currently passes.
- A table or column present in `schema.sql` with no migration, or in a migration
  with no `schema.sql` declaration, is a defect.
- Reviewers check both paths for any change touching `schema.sql` or
  `teleclaude/core/migrations/`: would this apply cleanly to a database that has
  the table already, and would a database created purely from `schema.sql` be
  complete without it.

## Exceptions

- None. A migration that cannot be made idempotent is a migration whose target
  shape is wrong.

## See Also

- docs/project/policy/single-database.md — which database a table belongs to, once it is established that it needs one.

---
description: The config context owns a validated, transaction-wide mutation boundary for machine configuration.
visibility: public
---

# Machine Config Write — Spec

## Required reads

@docs/local/spec/domain/config.md
@docs/local/spec/feature/config/atomic-project-config-write.md
@docs/local/spec/feature/config/machine-config-load.md

## What it is

The config context is the sole internal authority that mutates machine configuration. Agent surfaces and runtime components submit semantic operations and values; they never parse the backing file, mutate a caller-owned document, or supply a full-document replacement.

One mutation transaction owns the complete lifecycle:

1. acquire the stable per-file lock;
2. read and parse the latest committed document;
3. apply the requested semantic mutation;
4. validate the complete candidate through the typed machine-config schema;
5. serialize the candidate to a unique sibling temporary file, flush it, and durably sync it;
6. atomically replace the target and release the lock.

Any failure before replacement leaves the committed target unchanged. Successful return means the committed document has already passed validation.
The lock spanning the read through replacement makes concurrent accepted
mutations compose over the latest committed document instead of losing an
earlier mutation. If serialization, flushing, syncing, or replacement fails,
the writer removes its temporary file when present, re-raises the original
failure, and leaves the prior committed target unchanged.

Every computer-document write, including initial generation and a migration
that persists a changed document, emits exactly one editor schema modeline as
the first line. Its relative reference names the published computer schema in
the home's schema directory. Existing documents acquire the reference on their
next write; reading, initializing an existing document, and an already-current
migration leave them untouched.

## Canonical fields

### Mutation request

- A named config-context operation.
- The typed values required by that operation.
- No caller-owned raw document and no caller-selected machine-config path.

### Use cases

#### UC-MCW-1: A valid mutation commits atomically

#### UC-MCW-2: An invalid candidate leaves committed state unchanged

#### UC-MCW-3: Concurrent mutations preserve both outcomes

#### UC-MCW-4: Non-config contexts hold no file-write authority

#### UC-MCW-5: Successful mutation requires no validation follow-up

#### UC-MCW-6: A persistence failure preserves the prior target

#### UC-MCW-7: Machine-config writes emit no configuration event in v1

### Cross-context references

- `telec config`, the setup wizard, installation, migrations, and the TUI are callers of config-owned operations; none owns persistence.
- Discord provider identifiers are integration reflection state and are persisted through the database reflection-state repository rather than through this contract.

## Allowed values

- Mutation operations are the named operations published by the config context.
- Mutation values are typed by the owning operation and validated as part of the complete candidate.
- Arbitrary full-document replacement is not an allowed caller operation.

## Known caveats

- Data-file syncing does not guarantee containing-directory metadata durability on every filesystem stack.
- The v1 config watcher owns runtime reload after replacement; the writer emits no domain event.

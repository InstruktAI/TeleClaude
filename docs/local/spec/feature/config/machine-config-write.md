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

```gherkin
Given a supported semantic mutation and valid values
When the config context applies the mutation
Then it holds the machine-config lock across reading, mutation, validation, and replacement
And validates the complete candidate before persistence
And writes and durably syncs a unique temporary file
And atomically replaces the committed machine configuration
And returns the committed result
```

#### UC-MCW-2: An invalid candidate leaves committed state unchanged

```gherkin
Given a semantic mutation would produce schema-invalid machine configuration
When the config context validates the complete candidate
Then it rejects the mutation with the schema error
And no replacement occurs
And the committed machine configuration remains byte-for-byte unchanged
```

#### UC-MCW-3: Concurrent mutations preserve both outcomes

```gherkin
Given two runtime callers concurrently request independent machine-config mutations
When the config context executes both operations
Then one transaction completes before the other reads committed state
And the second transaction applies its mutation over the first committed result
And neither accepted mutation is lost
```

#### UC-MCW-4: Non-config contexts hold no file-write authority

```gherkin
Given a runtime component needs a declared machine-config change
When it requests that change
Then it calls a named config-context operation with semantic values
And it does not read, serialize, or replace the machine-config backing file
```

#### UC-MCW-5: Successful mutation requires no validation follow-up

```gherkin
Given the config context reports a machine-config mutation succeeded
When the calling agent or runtime component continues
Then it treats the returned state as the validated committed result
And it does not invoke a second validation operation as confirmation
```

#### UC-MCW-6: A persistence failure preserves the prior target

```gherkin
Given the config context has started serializing a valid candidate
And serialization, flushing, syncing, or replacement fails
When the transaction handles the failure
Then it removes its temporary file when present
And re-raises the original failure
And leaves the prior committed target unchanged
```

#### UC-MCW-7: Machine-config writes emit no configuration event in v1

```gherkin
Given a machine-config mutation has committed
When the transaction returns
Then no effective-configuration-updated event is emitted in v1
And runtime reload behavior remains owned by the existing config watcher and service lifecycle
```

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

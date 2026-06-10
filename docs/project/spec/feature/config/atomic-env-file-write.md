---
description: 'The env-file writer mutates `.env` atomically — dump line-edited content to a sibling temp file, durably flush, atomically replace, cleanup on failure — so per-section wizard writes satisfy the setup-wizard idempotency contract.'
visibility: 'public'
---

# Atomic Env File Write — Spec

## Required reads

- @docs/project/spec/feature/config/atomic-project-config-write.md
- @docs/project/spec/feature/config/setup-wizard.md
- @docs/project/spec/teleclaude-config.md

## What it is

The env-file writer in the config bounded context is the sanctioned write path for the `.env` file that holds adapter
credentials, AI/voice keys, and runtime env overrides. In v1 the
writer is line-edit-then-rewrite — it reads, mutates, and writes back
against the same path. That non-atomic shape can leave
the `.env` file partially written if the process is killed mid-write
and breaks the setup-wizard's per-section atomicity contract
(`setup-wizard` UC-WIZ-3, UC-WIZ-5).

This spec captures the **target** v1 contract: the env-file writer writes
atomically via the same tmp-file + flush+fsync + atomic rename pattern
used by the project-config writer.

The contract holds three guarantees, identical in shape to
`atomic-project-config-write`:

1. **Atomic visibility.** A concurrent reader on the `.env` file sees
   either the previous contents or the fully-written new contents,
   never a partial write. The line-edited content is dumped to a
   `.tmp` sibling first; only after the buffer is flushed and
   durably syncing to kernel does the atomic rename move the tmp file into place.

2. **Crash cleanup of the tmp sibling.** If anything between opening
   the tmp file and the rename raises (disk full, permission failure,
   fsync failure), the writer unlinks the tmp file before re-raising.
   The original target file is left untouched.

3. **Same surface, same validation.** The existing input validation
   (`name` cannot contain `\r\n=`, `value` cannot contain `\r\n`)
   and the existing in-process environment update side-effect
   stay intact. Only the on-disk write step changes to the atomic-replace pattern.

The helper's interface does not change: it takes the var name, value, and an
optional env-file path override, and returns the written path.

## Canonical fields

### Use cases

#### UC-AEFW-1: Successful set replaces target file atomically

```
Given a valid (name, value) pair and the resolved .env path
And the target path may or may not already exist
When the env-file writer runs
Then the existing line list is read (if the file exists) and edited
And a tmp_path of .env.tmp (or equivalent .tmp sibling) is computed
And the tmp file is opened for write with utf-8 encoding
And the line-edited content is written to the tmp file
And the output is flushed and durably synced at the kernel level
And the tmp file is atomically renamed into place at the target path
And the in-process environment is updated with the new value
And the call returns the resolved target path
And no concurrent reader observes a partially-written .env file
```

#### UC-AEFW-2: Failure mid-write cleans up tmp and re-raises

```
Given the env-file writer has opened the tmp file and started writing
And an exception occurs (disk full, permission failure, fsync failure)
When an exception is raised mid-write
Then the temp file's presence is checked
And the partial temp file is removed if present
And the original exception is re-raised unchanged
And the target .env file is unchanged from its prior state
And the in-process environment is NOT updated (the update only fires after a successful write)
```

#### UC-AEFW-3: Input validation runs before any file I/O

```
Given a (name, value) pair where name contains `=`, `\r`, or `\n`
When the env-file writer runs
Then a validation error is raised before any tmp file is opened
And the on-disk .env file is unchanged
And the in-process environment is unchanged

Given a (name, value) pair where value contains `\r` or `\n`
When the env-file writer runs
Then a validation error is raised before any tmp file is opened
And the on-disk .env file is unchanged
And the in-process environment is unchanged
```

#### UC-AEFW-4: Idempotent set is byte-stable through atomic replace

```
Given a .env file containing a line `TELEGRAM_BOT_TOKEN=abc123`
When the env-file writer runs with ("TELEGRAM_BOT_TOKEN", "abc123")
Then the line-edit step replaces the existing line with the identical content
And the atomic-replace pattern writes a byte-stable file
And the in-process environment is updated: TELEGRAM_BOT_TOKEN = "abc123"
And the call returns successfully
```

### Cross-context references

- The setup wizard (per `project/spec/feature/config/setup-wizard`) is the
  primary consumer that depends on this atomicity contract via UC-WIZ-3
  and UC-WIZ-5.
- A parallel env-file writer used by the `telec config env set` surface
  may converge on this same atomic writer. The contract above mandates the
  shape; if a second writer is unified, the same contract applies.

## Allowed values

- `name`: env var name; cannot contain `\r`, `\n`, or `=`.
- `value`: env var value; cannot contain `\r` or `\n`.
- `env_path`: optional override; defaults to the value resolved by
  `resolve_env_file_path` (honours `TELECLAUDE_ENV_PATH`).

## Known caveats

- **In-process env update is post-write only.** The in-process environment update
  fires only after the atomic replace succeeds. If the write fails,
  the in-process environment is also unchanged (UC-AEFW-2).
- **No locking against concurrent writers.** Two concurrent
  env-file writer calls on the same path race in the tmp-file step;
  the atomic-rename contract still guarantees the FINAL on-disk file
  is one complete write, but which writer's content wins depends on
  scheduling.
- **fsync covers data, not the directory entry.** Same caveat as
  `atomic-project-config-write` — filesystem-stack durability beyond
  fsync of the file is the operator's filesystem choice.
- **No diff-and-skip optimisation.** The helper always rewrites the
  file even when the line-edited content matches the on-disk content
  (UC-AEFW-4). The atomic-replace contract treats every call as a
  real write.

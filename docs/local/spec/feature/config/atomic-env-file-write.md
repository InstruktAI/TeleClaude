---
description: 'The env-file writer mutates `.env` atomically — dump line-edited content to a sibling temp file, durably flush, atomically replace, cleanup on failure — so per-section wizard writes satisfy the setup-wizard idempotency contract.'
visibility: 'public'
---

# Atomic Env File Write — Spec

## Required reads

- @docs/local/spec/feature/config/atomic-project-config-write.md
- @docs/local/spec/feature/config/setup-wizard.md
- @docs/local/spec/teleclaude-config.md

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

#### UC-AEFW-2: Failure mid-write cleans up tmp and re-raises

#### UC-AEFW-3: Input validation runs before any file I/O

#### UC-AEFW-4: Idempotent set is byte-stable through atomic replace

### Cross-context references

- The setup wizard (per `local/projects/teleclaude/spec/feature/config/setup-wizard`) is the
  primary consumer that depends on this atomicity contract via UC-WIZ-3
  and UC-WIZ-5.
- A parallel env-file writer used by the `telec config env set` surface
  may converge on this same atomic writer. The contract above mandates the
  shape; if a second writer is unified, the same contract applies.

<!-- planned:issue-129 -->

### Protected global GitHub App-key path

For a key name the config owner classifies as a global GitHub App private key,
the environment writer applies the protected-file rules from
`local/projects/teleclaude/spec/domain/config`: an existing store must pass its
custody check before mutation, and unsafe storage refuses without chmod,
migration or changes to unrelated entries. A protected set may create an
absent `.env` with owner-only mode; clearing an absent store creates no file.
Generic values keep the writer's existing line-preserving and newline rules.
Catalog classification and cross-file coordination belong to
`local/projects/teleclaude/spec/domain/config`; this writer atomically replaces
only the `.env` file.

The protected path creates its sibling temporary with owner-only mode before
the first content write. A new file uses mode `0600`; replacement preserves
the verified existing target mode. Flush, fsync, atomic replacement and
failure cleanup remain in the existing writer. This closes the interval in
which a secret-bearing temporary could inherit a more permissive umask.
<!-- /planned:issue-129 -->

## Allowed values

- `name`: env var name; cannot contain `\r`, `\n`, or `=`.
- `value`: env var value; cannot contain `\r` or `\n`.

- `env_path`: optional override; defaults to the value resolved by
  `resolve_env_file_path` — the project `.env` at the repository root.

## Known caveats

- **Protected temporary content is currently written before chmod.**
  `FileTransaction.replace_text` writes the sibling temporary first and only
  then applies the existing target or requested creation mode. A newly written
  secret-bearing temporary can therefore inherit a more permissive umask
  before owner-only mode is applied; passing `creation_mode=0600` alone does
  not prevent that interval. Owner-only mode must be established on the
  temporary before its first content write for protected data. Atomic replace
  and cleanup after failure do not close the earlier permission window.
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

---
id: 'project/spec/feature/config/atomic-env-file-write'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by:
  - 'install-wizard-enrichment'
description: 'set_env_var writes the .env file atomically — dump line-edited content to a `.tmp` sibling, flush+fsync, os.replace into place, cleanup on failure — so per-section wizard writes satisfy the setup-wizard idempotency contract.'
---

# Atomic Env File Write — Spec

## Required reads

- @docs/project/spec/feature/config/atomic-project-config-write.md
- @docs/project/spec/feature/config/setup-wizard.md
- @docs/project/spec/teleclaude-config.md

## What it is

`set_env_var` (in `teleclaude/cli/config_handlers.py`) is the
sanctioned write path for the `.env` file that holds adapter
credentials, AI/voice keys, and runtime env overrides. In v1 the
writer is line-edit-then-rewrite — it `read_text` / line-mutates /
`write_text` against the same path. That non-atomic shape can leave
the `.env` file partially written if the process is killed mid-write
and breaks the setup-wizard's per-section atomicity contract
(`setup-wizard` UC-WIZ-3, UC-WIZ-5).

This spec captures the **target** v1 contract: `set_env_var` writes
atomically via the same tmp-file + flush+fsync + `os.replace` pattern
used by `save_project_config`.

The contract holds three guarantees, identical in shape to
`atomic-project-config-write`:

1. **Atomic visibility.** A concurrent reader on the `.env` file sees
   either the previous contents or the fully-written new contents,
   never a partial write. The line-edited content is dumped to a
   `.tmp` sibling first; only after the buffer is flushed and
   `os.fsync` returns does `os.replace` move the tmp file into place.

2. **Crash cleanup of the tmp sibling.** If anything between opening
   the tmp file and the rename raises (disk full, permission failure,
   fsync failure), the writer unlinks the tmp file before re-raising.
   The original target file is left untouched.

3. **Same surface, same validation.** The existing input validation
   (`name` cannot contain `\r\n=`, `value` cannot contain `\r\n`)
   and the existing in-process `os.environ[name] = value` side-effect
   stay intact. Only the on-disk write step changes from
   `target.write_text(...)` to the atomic-replace pattern.

The helper signature does not change: `set_env_var(name: str,
value: str, env_path: Path | None = None) -> Path`.

## Canonical fields

### Use cases

#### UC-AEFW-1: Successful set replaces target file atomically

```
Given a valid (name, value) pair and the resolved .env path
And the target path may or may not already exist
When set_env_var(name, value) runs
Then the existing line list is read (if the file exists) and edited
And a tmp_path of .env.tmp (or equivalent .tmp sibling) is computed
And the tmp file is opened for write with utf-8 encoding
And the line-edited content is written to the tmp file
And f.flush() and os.fsync(f.fileno()) ensure kernel-level durability
And os.replace(tmp_path, target) atomically moves the tmp file into place
And os.environ[name] = value mutates the in-process environment
And the call returns the resolved target path
And no concurrent reader observes a partially-written .env file
```

#### UC-AEFW-2: Failure mid-write cleans up tmp and re-raises

```
Given set_env_var has opened the tmp file and started writing
And an exception occurs (disk full, permission failure, fsync failure)
When control reaches the except block
Then tmp_path.exists() is checked
And tmp_path.unlink() removes the partial tmp file if present
And the original exception is re-raised unchanged via bare `raise`
And the target .env file is unchanged from its prior state
And os.environ[name] is NOT mutated (the mutation only fires after a successful write)
```

#### UC-AEFW-3: Input validation runs before any file I/O

```
Given a (name, value) pair where name contains `=`, `\r`, or `\n`
When set_env_var(name, value) runs
Then ValueError is raised before any tmp file is opened
And the on-disk .env file is unchanged
And os.environ is unchanged

Given a (name, value) pair where value contains `\r` or `\n`
When set_env_var(name, value) runs
Then ValueError is raised before any tmp file is opened
And the on-disk .env file is unchanged
And os.environ is unchanged
```

#### UC-AEFW-4: Idempotent set is byte-stable through atomic replace

```
Given a .env file containing a line `TELEGRAM_BOT_TOKEN=abc123`
When set_env_var("TELEGRAM_BOT_TOKEN", "abc123") runs
Then the line-edit step replaces the existing line with the identical content
And the atomic-replace pattern writes a byte-stable file
And os.environ["TELEGRAM_BOT_TOKEN"] = "abc123"
And the call returns successfully
```

### Implementation pointers (v1, target)

- Implementation lives at `teleclaude/cli/config_handlers.py:set_env_var`.
- The existing line-edit loop (read + iterate + replace-or-append)
  stays intact; only the final write step changes from
  `target.write_text(...)` to the tmp-file + flush+fsync +
  `os.replace` pattern.
- The same atomic-replace pattern lives in
  `config/loader.py:save_project_config` and the new
  `save_machine_config` (per `machine-config-write`). The three
  writers may share a small `_atomic_write_text` helper or each
  reproduce the pattern in-place — placement is a plan-phase choice.

### Cross-context references

- The wizard (per `project/spec/feature/config/setup-wizard`) is the
  primary v1 consumer that depends on this atomicity contract via
  UC-WIZ-3 and UC-WIZ-5.
- `cli/config_cli.py:_write_env_var` is a parallel env-file writer in
  the legacy `telec config env set` path. Whether that helper is
  unified with `set_env_var` (so both use the same atomic writer) is
  a plan-phase decision. The spec above mandates the contract for
  `set_env_var` only; if `_write_env_var` is also unified, the same
  contract applies.

## Allowed values

- `name`: env var name; cannot contain `\r`, `\n`, or `=`.
- `value`: env var value; cannot contain `\r` or `\n`.
- `env_path`: optional override; defaults to the value resolved by
  `resolve_env_file_path` (honours `TELECLAUDE_ENV_PATH`).

## Known caveats

- **In-process env mutation is post-write only.** `os.environ[name] = value`
  fires only after the atomic replace succeeds. If the write fails,
  the in-process environment is also unchanged (UC-AEFW-2).
- **No locking against concurrent writers.** Two concurrent
  `set_env_var` calls on the same path race in the tmp-file step;
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

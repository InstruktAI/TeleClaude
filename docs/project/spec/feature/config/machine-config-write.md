---
id: 'project/spec/feature/config/machine-config-write'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'The machine-config writer mutates `config.yml` atomically — dump to a sibling temp file, durably flush, atomically replace, cleanup on failure — mirroring the project-config writer but targeting the machine config aggregate.'
---

# Machine Config Write — Spec

## Required reads

- @docs/project/spec/feature/config/atomic-project-config-write.md
- @docs/project/spec/feature/config/machine-config-load.md
- @docs/project/spec/domain/config.md

## What it is

The machine-config writer is the sanctioned write path for the machine
`config.yml` file. It complements the project-config writer (which
targets the project overlay YAML) by providing the same atomic-replace
contract for the file the machine-config loader consumes at process
start.

The helper operates on the **raw YAML mapping** (a `dict`), not on the
loaded runtime configuration aggregate. This is a deliberate constraint:
the loaded aggregate contains runtime-derived fields that are not part
of the documented `config.yml` schema and that the loader rejects on
re-read — for example `computer.tmux_binary` (resolved by runtime
policy, not user-configurable) and per-agent `binary` / `profiles`
fields (system-controlled, injected at load time). Persisting the
loaded aggregate as-is would write a file the next load refuses,
breaking the PRD's "make start comes up cleanly after the wizard"
contract.

Callers therefore read the existing YAML as a raw mapping, mutate the
specific keys they own (e.g. `computer.name`), and pass the mutated
mapping to the writer. The on-disk file thus contains only documented
`config.yml` keys.

The contract holds four guarantees:

1. **Atomic visibility.** A concurrent reader on `config.yml` sees
   either the previous contents or the fully-written new contents,
   never a partial write. The write happens to a `.tmp` sibling first;
   the atomic rename happens only after the buffer is
   flushed and durably synced at the kernel level.

2. **Crash cleanup of the tmp sibling.** If anything between opening
   the tmp file and the rename raises (disk full, permission failure,
   serialisation error mid-dump, fsync failure), the writer unlinks
   the tmp file before re-raising. The target file is left untouched.

3. **Raw-mapping input only.** The helper accepts a raw YAML mapping
   (the dict the YAML parser produces). It does
   **not** accept the loaded runtime configuration aggregate — see above.

4. **Caller-validated input.** The helper does NOT validate that the
   supplied mapping satisfies the documented `config.yml` schema or
   the invariants in `agents-inventory-requirement`. The caller (the
   wizard) is responsible for keeping the mapping reloadable. The
   wizard's discipline is: after a successful machine-config write,
   attempt to reload the file via the existing machine-config loader;
   the section is considered `configured` only when the reload
   succeeds. Reload failure surfaces as `invalid` per UC-WIZ-6.

The helper is sync, takes a `Path` and a raw mapping (`dict`), and
returns `None` on success.

## Canonical fields

### Use cases

#### UC-MCW-1: Successful write replaces target file atomically

```
Given a raw config mapping and target path ~/.teleclaude/config.yml
And the mapping contains only documented config.yml keys (no runtime-derived fields)
And the target path may or may not already exist
When the machine-config writer runs
Then a sibling tmp path of ~/.teleclaude/config.tmp is derived from the target path
And the mapping is serialized as YAML and written to the tmp file
And the output is flushed and durably synced at the kernel level
And the tmp file is atomically renamed into place at the target path
And the call returns None
And no concurrent reader observes a partially-written config.yml
```

#### UC-MCW-2: Failure mid-write cleans up tmp and re-raises

```
Given the machine-config writer has opened the tmp file and started writing
And an exception occurs (disk full during write, fsync failure, etc.)
When an exception occurs mid-write
Then the temp file's presence is checked
And the partial temp file is removed if present
And the original exception is re-raised unchanged
And the target path is unchanged from its prior state
```

#### UC-MCW-3: Raw-mapping contract excludes runtime-derived fields

```
Given a caller passes the loaded typed config object directly (not a raw mapping)
When the machine-config writer runs against that input
Then the writer's input contract is violated
And the loaded tree contains runtime-derived fields like computer.tmux_binary
  and the agent binary field that the machine-config loader rejects on reload
And the resulting file is not reloadable

Given a caller passes a raw mapping that omits runtime-derived fields
And contains a valid documented config.yml schema (per teleclaude-config)
When the machine-config writer runs
Then the on-disk file reflects exactly the supplied mapping
And the next load via the existing machine-config loader succeeds
And the caller is responsible for keeping the mapping reloadable
```

#### UC-MCW-5: Caller validates reloadability after write

```
Given a wizard step has called the machine-config writer with (path, raw_mapping)
And the call returned successfully
When the wizard re-derives the section's status for UC-WIZ-5/UC-WIZ-6
Then the wizard attempts to reload the file via the existing machine-config loader
And on successful reload the section status is `configured`
And on reload failure the section status is `invalid`
And the failure does NOT cause the writer to roll back —
  rollback is the operator's responsibility (re-open the wizard, correct the input)
```

#### UC-MCW-4: No `config.effective.updated` event in v1

```
Given the machine-config writer has successfully completed
When the function returns
Then no `config.effective.updated` event is published in v1
And v1 consumers re-read `config.yml` at startup (daemon) or per-invocation (CLI)
And the operator triggers reload via `make restart` or daemon restart, not via an event
And future v1→v2 migration may introduce the filesystem-watcher event without changing this writer's contract
```

### Cross-context references

- The setup wizard (per `project/spec/feature/config/setup-wizard`) is
  the consumer. The wizard's "Configure System Identity" step (and any
  future machine-level wizard step) routes its writes through this
  helper. Release-channel state lives in the project deployment block
  (project YAML, written by the project-config writer), not in machine
  config, so it is not a consumer of this helper.
- `telec config patch` is out of scope for this delivery and is not
  changed by this spec. A future delivery may route its machine-config
  writes through this writer; that delivery would update this spec and
  `telec config patch` together.
- The atomic-replace contract is one of the inputs into a future
  filesystem-watcher event in the config bounded context. Layering event
  emission on top of this writer does not change the contract above.

## Allowed values

- `path`: any writable filesystem path; the helper does not constrain
  filename or directory.
- `raw_config`: a raw YAML mapping (`dict`) that contains ONLY
  documented `config.yml` keys (per
  `project/spec/teleclaude-config#Daemon-runtime-config-keys`). The
  loaded typed config object is **NOT** an allowed input — see
  the "What it is" section and UC-MCW-3 for why. The helper does not
  enforce runtime type checks; the caller is responsible for keeping
  the mapping reloadable.

## Known caveats

- **No parent-directory creation.** The machine-config writer assumes the
  parent directory of `path` already exists. If it does not,
  `open(tmp_path, "w")` raises `FileNotFoundError`. Callers that may
  target a fresh `~/.teleclaude/` tree must create the directory tree
  themselves.
- **No locking against concurrent writers.** Two concurrent
  machine-config writer calls on the same path race in the tmp-file
  step; the atomic-rename contract still guarantees the final on-disk
  file is one complete write, but which writer's content wins depends
  on scheduling.
- **fsync covers data, not the directory entry.** Same caveat as
  the project-config writer: filesystem-stack durability beyond `fsync` of
  the file is the operator's filesystem choice.
- **v1 does not emit `config.effective.updated`.** Per UC-MCW-4. The
  operator-visible reload story is `make restart` (or daemon restart);
  CLI invocations naturally re-read at module import.
- **No diff-and-skip optimisation.** The helper always rewrites the
  file even when the dumped payload matches the current on-disk
  content. The atomic-replace contract treats every call as a real
  write.

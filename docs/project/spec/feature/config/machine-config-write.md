---
id: 'project/spec/feature/config/machine-config-write'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by:
  - 'install-wizard-enrichment'
description: 'save_machine_config writes the machine `config.yml` atomically — dump to a `.tmp` sibling, flush+fsync, os.replace into place, cleanup on failure — mirroring save_project_config but targeting the dataclass-based machine Config tree loaded by teleclaude/config/__init__.py.'
---

# Machine Config Write — Spec

## Required reads

- @docs/project/spec/feature/config/atomic-project-config-write.md
- @docs/project/spec/feature/config/machine-config-load.md
- @docs/project/spec/domain/config.md

## What it is

`save_machine_config` is the sanctioned write path for the machine
`config.yml` file in v1. It complements `save_project_config` (which
targets the Pydantic-backed project YAML) by providing the same
atomic-replace contract for the file the dataclass-based loader at
`teleclaude/config/__init__.py` consumes at startup.

The helper operates on the **raw YAML mapping** (a `dict`), not on
the loaded `Config` dataclass tree. This is a deliberate constraint:
the loaded tree contains runtime-derived fields that are not part of
the documented `config.yml` schema and that the loader rejects on
re-read — for example `computer.tmux_binary` (resolved by runtime
policy, not user-configurable) and `AgentConfig.binary` /
`AgentConfig.profiles` (system-controlled, injected at load time).
Persisting the dataclass tree as-is would write a file the next load
refuses, breaking the PRD's "make start comes up cleanly after the
wizard" contract.

Callers therefore read the existing YAML as a raw mapping, mutate the
specific keys they own (e.g. `computer.name`), and pass the mutated
mapping to `save_machine_config`. The on-disk file thus contains only
documented `config.yml` keys.

The contract holds four guarantees:

1. **Atomic visibility.** A concurrent reader on `config.yml` sees
   either the previous contents or the fully-written new contents,
   never a partial write. The write happens to a `.tmp` sibling first;
   `os.replace` performs the atomic rename only after the buffer is
   flushed and `os.fsync` returns.

2. **Crash cleanup of the tmp sibling.** If anything between opening
   the tmp file and the rename raises (disk full, permission failure,
   serialisation error mid-dump, fsync failure), the writer unlinks
   the tmp file before re-raising. The target file is left untouched.

3. **Raw-mapping input only.** The helper accepts a raw YAML mapping
   produced by `yaml.safe_load` (or equivalently constructed). It does
   **not** accept the parsed `Config` dataclass tree — see above.

4. **Caller-validated input.** The helper does NOT validate that the
   supplied mapping satisfies the documented `config.yml` schema or
   the invariants in `agents-inventory-requirement`. The caller (the
   wizard) is responsible for keeping the mapping reloadable. The
   wizard's discipline is: after a successful `save_machine_config`,
   attempt to reload the file via the existing machine-config loader;
   the section is considered `configured` only when the reload
   succeeds. Reload failure surfaces as `invalid` per UC-WIZ-6.

The helper is sync, takes a `Path` and a raw mapping (`dict`), and
returns `None` on success.

## Canonical fields

### Use cases

#### UC-MCW-1: Successful write replaces target file atomically

```
Given a raw config mapping (dict produced by yaml.safe_load) and target path ~/.teleclaude/config.yml
And the mapping contains only documented config.yml keys (no runtime-derived fields)
And the target path may or may not already exist
When save_machine_config(path, raw_mapping) runs
Then a tmp_path of ~/.teleclaude/config.tmp is computed via path.with_suffix(".tmp")
And the tmp file is opened for write with utf-8 encoding
And yaml.safe_dump writes the mapping to the tmp file
And f.flush() and os.fsync(f.fileno()) ensure kernel-level durability
And os.replace(tmp_path, path) atomically moves the tmp file into place
And the call returns None
And no concurrent reader observes a partially-written config.yml
```

#### UC-MCW-2: Failure mid-write cleans up tmp and re-raises

```
Given save_machine_config has opened the tmp file and started writing
And an exception occurs (disk full during write, fsync failure, etc.)
When control reaches the except block
Then tmp_path.exists() is checked
And tmp_path.unlink() removes the partial tmp file if present
And the original exception is re-raised unchanged via bare `raise`
And the target path is unchanged from its prior state
```

#### UC-MCW-3: Raw-mapping contract excludes runtime-derived fields

```
Given a caller passes the loaded Config dataclass tree directly (not a raw mapping)
When save_machine_config runs against that input
Then the writer's input contract is violated
And the loaded tree contains runtime-derived fields like computer.tmux_binary
  and AgentConfig.binary that the machine-config loader rejects on reload
And the resulting file is not reloadable

Given a caller passes a raw mapping that omits runtime-derived fields
And contains a valid documented config.yml schema (per teleclaude-config)
When save_machine_config runs
Then the on-disk file reflects exactly the supplied mapping
And the next load via the existing machine-config loader succeeds
And the caller is responsible for keeping the mapping reloadable
```

#### UC-MCW-5: Caller validates reloadability after write

```
Given a wizard step has called save_machine_config(path, raw_mapping)
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
Given save_machine_config has successfully completed
When the function returns
Then no `config.effective.updated` event is published in v1
And v1 consumers re-read `config.yml` at startup (daemon) or per-invocation (CLI)
And the operator triggers reload via `make restart` or daemon restart, not via an event
And future v1→v2 migration may introduce the filesystem-watcher event without changing this writer's contract
```

### Implementation pointers (v1, target)

- The implementation lives alongside `save_project_config` in the v1
  config writer module (current home: `teleclaude/config/loader.py`).
  Placement is chosen for symmetry with the existing atomic-write
  helper.
- Serialisation is `yaml.safe_dump` of the raw mapping the caller
  supplies. No dataclass-to-dict conversion is needed (or allowed)
  inside the helper — the caller controls the on-disk shape.
- The matching read path is the existing machine-config loader in
  `teleclaude/config/__init__.py` (per `machine-config-load`). The
  wizard reads the existing YAML via `yaml.safe_load`, mutates the
  keys it owns in the resulting mapping, and passes the mutated
  mapping to `save_machine_config`.
- Runtime-derived fields the caller MUST NOT include in the mapping
  (non-exhaustive; verify against the loader at plan time): the
  `computer.tmux_binary` field, and every `agents.<name>.binary` /
  `agents.<name>.profiles` / `agents.<name>.session_dir` /
  `agents.<name>.log_pattern` / `agents.<name>.model_flags` /
  `agents.<name>.exec_subcommand` field. These are system-controlled
  and resolved at load time.

### Cross-context references

- The wizard (per `project/spec/feature/config/setup-wizard`) is the
  v1 consumer. The wizard's "Configure System Identity" step (and
  any future machine-level wizard step) invokes this helper.
  Release-channel state lives in `ProjectConfig.deployment` (project
  YAML, written by `save_project_config`), NOT in machine config, so
  it is not a consumer of this helper.
- `telec config patch` is out of scope for this delivery. The
  current implementation raw-merges YAML without using this helper
  and is not changed by this spec. A future delivery may route its
  `config.yml`-targeted writes through `save_machine_config`; that
  delivery would update this spec and `telec config patch` together.
- The atomic-replace contract is one of the inputs into a future v2
  filesystem-watcher event. The v2 cutover may layer event emission
  on top of this helper; the v1 contract above does not change.

## Allowed values

- `path`: any writable filesystem path; the helper does not constrain
  filename or directory.
- `raw_config`: a raw YAML mapping (`dict`) that contains ONLY
  documented `config.yml` keys (per
  `project/spec/teleclaude-config#Daemon-runtime-config-keys`). The
  loaded `Config` dataclass tree is **NOT** an allowed input — see
  the "What it is" section and UC-MCW-3 for why. The helper does not
  enforce runtime type checks; the caller is responsible for keeping
  the mapping reloadable.

## Known caveats

- **No parent-directory creation.** `save_machine_config` assumes the
  parent directory of `path` already exists. If it does not,
  `open(tmp_path, "w")` raises `FileNotFoundError`. Callers that may
  target a fresh `~/.teleclaude/` tree must create the directory tree
  themselves.
- **No locking against concurrent writers.** Two concurrent
  `save_machine_config` calls on the same path race in the tmp-file
  step; the atomic-rename contract still guarantees the final on-disk
  file is one complete write, but which writer's content wins depends
  on scheduling.
- **fsync covers data, not the directory entry.** Same caveat as
  `save_project_config`: filesystem-stack durability beyond `fsync` of
  the file is the operator's filesystem choice.
- **v1 does not emit `config.effective.updated`.** Per UC-MCW-4. The
  operator-visible reload story is `make restart` (or daemon restart);
  CLI invocations naturally re-read at module import.
- **No diff-and-skip optimisation.** The helper always rewrites the
  file even when the dumped payload matches the current on-disk
  content. The atomic-replace contract treats every call as a real
  write.

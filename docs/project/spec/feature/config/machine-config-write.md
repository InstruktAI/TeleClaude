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
atomic-replace contract for the dataclass-backed machine config tree
loaded by `teleclaude/config/__init__.py`.

The contract holds three guarantees, identical in shape to
`save_project_config`:

1. **Atomic visibility.** A concurrent reader on `config.yml` sees
   either the previous contents or the fully-written new contents,
   never a partial write. The write happens to a `.tmp` sibling first;
   `os.replace` performs the atomic rename only after the buffer is
   flushed and `os.fsync` returns.

2. **Crash cleanup of the tmp sibling.** If anything between opening
   the tmp file and the rename raises (disk full, permission failure,
   serialisation error mid-dump, fsync failure), the writer unlinks
   the tmp file before re-raising. The target file is left untouched.

3. **Caller-validated input.** The helper does NOT re-validate the
   supplied dataclass tree. The caller (the wizard or
   `telec config patch`) is responsible for ensuring the tree
   satisfies the documented `config.yml` schema in
   `project/spec/teleclaude-config#Daemon-runtime-config-keys` and the
   invariants in `agents-inventory-requirement` before invoking the
   helper.

The helper is sync, takes a `Path` and the machine `Config` dataclass
tree (or a serialisable dict equivalent), and returns `None` on
success. There is no read-modify-write helper at this layer; callers
that need to edit a value first call the existing machine-config
loader, mutate the returned tree, then call `save_machine_config`.

## Canonical fields

### Use cases

#### UC-MCW-1: Successful write replaces target file atomically

```
Given a valid machine Config dataclass tree and target path ~/.teleclaude/config.yml
And the target path may or may not already exist
When save_machine_config(path, config) runs
Then the dataclass tree is serialised to a YAML-safe dict via the project's
  established dataclass→dict helper
And a tmp_path of ~/.teleclaude/config.tmp is computed via path.with_suffix(".tmp")
And the tmp file is opened for write with utf-8 encoding
And yaml.safe_dump writes the payload to the tmp file
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

#### UC-MCW-3: Caller controls validation; save assumes input is valid

```
Given a caller passes a Config dataclass tree that has not been re-validated since mutation
When save_machine_config runs
Then save_machine_config does NOT re-run schema validation
And the tree is dumped as-is; the on-disk file reflects exactly the in-memory state
And the responsibility for invariants (e.g., agents-inventory-requirement) lies with the caller
  before invoking save_machine_config
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
- Serialisation uses the project's documented dataclass-to-dict helper
  (whichever convention the plan phase grounds against — `dataclasses.asdict`
  or an equivalent) followed by `yaml.safe_dump`. JSON-mode coercion is not
  required because the machine `Config` tree does not contain
  Pydantic-only types.
- The matching read path is the existing machine-config loader in
  `teleclaude/config/__init__.py` (per `machine-config-load`).

### Cross-context references

- The wizard (per `project/spec/feature/config/setup-wizard`) is the
  primary v1 consumer. The wizard's "Configure System Identity" and
  "Configure Release Channel" steps invoke this helper.
  
  Note: as of the source PRD for this spec the release-channel field
  lives in `ProjectConfig.deployment` (project YAML, written by
  `save_project_config`); only computer-identity and other machine
  fields flow through `save_machine_config`. If a future delivery
  promotes the release channel into machine config, that delivery
  updates both the wizard and this spec.
- `telec config patch` (the non-interactive surface) is the secondary
  consumer: when its target keys belong to `config.yml`, it routes
  writes through this helper.
- The atomic-replace contract is one of the inputs into a future v2
  filesystem-watcher event. The v2 cutover may layer event emission
  on top of this helper; the v1 contract above does not change.

## Allowed values

- `path`: any writable filesystem path; the helper does not constrain
  filename or directory.
- `config`: the machine `Config` dataclass tree (or a serialisable
  dict equivalent the plan phase grounds against). The helper does not
  enforce runtime type checks.

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

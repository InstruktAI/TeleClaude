---
id: 'project/spec/feature/config/atomic-project-config-write'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'save_project_config writes the project teleclaude.yml atomically — dump to a .tmp sibling, flush+fsync, os.replace into place, cleanup on failure — using model_dump(mode="json", exclude_defaults=True) for minimal output.'
---

# Atomic Project Config Write — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

`save_project_config` is the only sanctioned write path for a project's
`teleclaude.yml` in v1. It serialises a validated `ProjectConfig` instance
to YAML and replaces the on-disk file atomically. The contract holds three
guarantees:

1. **Atomic visibility.** A concurrent reader on the same path sees either
   the previous file contents or the fully-written new contents, never a
   partial write. The write happens to a `.tmp` sibling first; only after
   the buffer is flushed to the kernel and `os.fsync` returns does
   `os.replace` move the tmp file into place. On POSIX, `os.replace` is the
   atomic rename system call.

2. **Crash cleanup of the tmp sibling.** If anything between opening the
   tmp file and the rename raises (disk full, permission failure,
   serialisation error mid-dump, fsync failure), the writer attempts to
   unlink the tmp file before re-raising. The original target file is left
   untouched.

3. **Minimal serialised form.** The payload sent to `yaml.safe_dump` is
   produced by `config.model_dump(mode="json", exclude_defaults=True)`.
   `mode="json"` coerces non-JSON-native types (e.g., enums, paths) into
   JSON-compatible primitives that `yaml.safe_dump` can handle without a
   custom representer. `exclude_defaults=True` drops every field whose
   current value equals its declared default, so the written file shows
   only operator-set values — no noise from default-factory blocks like
   `deployment: { channel: "alpha", pinned_minor: "" }`.

The helper is sync, takes a `Path` and a validated `ProjectConfig`, and
returns `None` on success. There is no read-modify-write helper at this
layer; callers that need to edit a value first call `load_project_config`,
mutate the returned model, then call `save_project_config`.

## Canonical fields

### Use cases

#### UC-CFG-WRITE-1: Successful write replaces target file atomically

```
Given a valid ProjectConfig instance and target path /repos/my-project/teleclaude.yml
And the target path may or may not already exist
When save_project_config(path, config) runs
Then config.model_dump(mode="json", exclude_defaults=True) produces a minimal dict
And a tmp_path of /repos/my-project/teleclaude.tmp is computed via path.with_suffix(".tmp")
And the tmp file is opened for write with utf-8 encoding
And yaml.safe_dump writes the payload to the tmp file
And f.flush() and os.fsync(f.fileno()) ensure kernel-level durability
And os.replace(tmp_path, path) atomically moves the tmp file into place
And the call returns None
And no concurrent reader observes a partially-written teleclaude.yml
```

#### UC-CFG-WRITE-2: Failure mid-write cleans up tmp and re-raises

```
Given save_project_config has opened the tmp file and started writing
And an exception occurs (disk full during write, fsync failure, etc.)
When control reaches the except block
Then tmp_path.exists() is checked
And tmp_path.unlink() removes the partial tmp file if present
And the original exception is re-raised unchanged via bare `raise`
And the target path is unchanged from its prior state
```

#### UC-CFG-WRITE-3: Defaults are stripped from the on-disk file

```
Given a ProjectConfig where deployment = DeploymentConfig() (default channel "alpha", empty pinned_minor)
And the operator set business.domains["primary"] = "instrukt.ai" but touched nothing else
When save_project_config runs
Then model_dump(mode="json", exclude_defaults=True) omits the entire `deployment` block
And omits any other block whose values match their defaults
And the resulting YAML contains only the business block (and any other non-default fields)
And re-loading the file via load_project_config rebuilds the same effective ProjectConfig
  because absent blocks reconstruct from default factories
```

#### UC-CFG-WRITE-4: JSON-mode dump produces YAML-safe primitives

```
Given a ProjectConfig that contains fields backed by non-native types (e.g., Path, enum)
When model_dump(mode="json", exclude_defaults=True) runs
Then Path values are serialised as strings
And enum values are serialised as their `.value` representation
And the resulting dict is composed entirely of JSON-native primitives (str, int, float, bool, list, dict, None)
And yaml.safe_dump accepts the dict without raising on unsupported types
```

#### UC-CFG-WRITE-5: Caller controls validation; save assumes input is valid

```
Given a caller passes a ProjectConfig that has not been re-validated since mutation
When save_project_config runs
Then save_project_config does NOT re-run Pydantic validation
And the model is dumped as-is; the on-disk file reflects exactly the in-memory state
And the responsibility for invariants (e.g., stable-channel pinning) lies with the caller
  before invoking save_project_config
```

### Implementation pointers (v1)

- `teleclaude/config/loader.py:69-82` — `save_project_config` body (model_dump, tmp_path computation, open+write+flush+fsync, os.replace, except-unlink cleanup).
- `teleclaude/config/loader.py:64-66` — `load_project_config` (the matching read path; round-tripping helper).
- `teleclaude/config/schema.py:308-324` — `ProjectConfig` (the model accepted by this writer).

### Cross-context references

- Operator tooling that mutates project config (the TUI wizard, `telec
config patch`, scripted setup) is expected to call `save_project_config`
  for project-level writes. There is no equivalent atomic helper for
  global or per-person overlays in v1.
- The atomic-replace contract is one of the inputs into the v2 `config`
  domain's `config.effective.updated` event: a filesystem watcher that sees
  an `os.replace`-driven inode change can rely on the new file being
  complete, not partially written.

## Allowed values

- `path`: any writable filesystem path; the helper does not constrain
  filename or directory.
- `config`: a `ProjectConfig` instance. Pydantic typing is enforced by the
  Python type system; runtime check is not performed inside the helper.

## Known caveats

- **No parent-directory creation.** `save_project_config` assumes the parent
  directory of `path` already exists. If it does not, `open(tmp_path, "w")`
  raises `FileNotFoundError`. Callers that may target a fresh project must
  create the directory tree themselves.
- **No locking against concurrent writers.** Two concurrent
  `save_project_config` calls on the same path race in the tmp-file step:
  the second writer's `open` truncates the first writer's tmp file. The
  atomic-rename contract still guarantees the FINAL on-disk file is one
  complete write, but which writer's content wins depends on scheduling.
- **fsync covers data, not the directory entry.** v1 fsyncs the tmp file
  descriptor but does not fsync the containing directory. On a crash
  immediately after `os.replace`, some filesystems may lose the rename
  metadata even though the data blocks are durable. The v1 contract is
  "atomic from the application's perspective"; storage-stack durability
  beyond fsync of the file is the operator's filesystem choice.
- **`with_suffix(".tmp")` replaces the entire extension.** A path like
  `teleclaude.yml` becomes `teleclaude.tmp`; a path with no extension
  becomes `<stem>.tmp`. Two project files with different extensions but
  the same stem would share a tmp path — relevant only if a project ever
  saved both `teleclaude.yml` and `teleclaude.yaml` side by side.
- **Cleanup itself can fail.** The except block calls `tmp_path.unlink()`
  only when `tmp_path.exists()` returns True; if the unlink itself raises
  (rare, e.g., permission revoked mid-failure), that secondary exception
  shadows the original via Python's `__context__` chain.
- **No-op for identical content.** The helper always rewrites the file
  even when the dumped payload matches the current on-disk content; there
  is no diff-and-skip optimisation. The atomic-replace contract treats
  every call as a real write.

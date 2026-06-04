---
id: 'project/spec/feature/config/atomic-project-config-write'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'The project-config writer mutates the project `teleclaude.yml` atomically — dump to a sibling temp file, durably flush, atomically replace, cleanup on failure — using a minimal serialization that omits default-valued fields.'
---

# Atomic Project Config Write — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The project-config writer is the only sanctioned write path for a project's
`teleclaude.yml`. It serialises a validated project overlay instance
to YAML and replaces the on-disk file atomically. The contract holds three
guarantees:

1. **Atomic visibility.** A concurrent reader on the same path sees either
   the previous file contents or the fully-written new contents, never a
   partial write. The write happens to a `.tmp` sibling first; only after
   the buffer is flushed to the kernel and durably synced does an atomic
   rename move the tmp file into place.

2. **Crash cleanup of the tmp sibling.** If anything between opening the
   tmp file and the rename raises (disk full, permission failure,
   serialisation error mid-dump, sync failure), the writer attempts to
   unlink the tmp file before re-raising. The original target file is left
   untouched.

3. **Minimal serialised form.** The project overlay is serialised to JSON-
   compatible primitives with default-valued fields excluded, so the written
   file shows only operator-set values — no noise from default-factory
   blocks like `deployment: { channel: "alpha", pinned_minor: "" }`.

The helper is sync, takes a path and a validated project overlay instance,
and returns on success. There is no read-modify-write helper at this
layer; callers that need to edit a value first load the overlay,
mutate the returned instance, then call the writer.

## Canonical fields

### Use cases

#### UC-CFG-WRITE-1: Successful write replaces target file atomically

```
Given a valid project overlay instance and target path /repos/my-project/teleclaude.yml
And the target path may or may not already exist
When the project-config writer runs
Then the overlay is serialised to a minimal JSON-compatible dict with defaults excluded
And a sibling tmp path /repos/my-project/teleclaude.tmp is derived from the target path
And the YAML payload is written to the tmp file
And the output is flushed and durably synced at the kernel level
And the tmp file is atomically renamed into place at the target path
And no concurrent reader observes a partially-written teleclaude.yml
```

#### UC-CFG-WRITE-2: Failure mid-write cleans up tmp and re-raises

```
Given the project-config writer has opened the tmp file and started writing
And an exception occurs (disk full during write, fsync failure, etc.)
When an exception occurs mid-write
Then the temp file's presence is checked
And the partial temp file is removed if present
And the original exception is re-raised unchanged
And the target path is unchanged from its prior state
```

#### UC-CFG-WRITE-3: Defaults are stripped from the on-disk file

```
Given a project overlay with default deployment settings (channel "alpha", empty pinned_minor)
And the operator set business.domains["primary"] = "instrukt.ai" but touched nothing else
When the project-config writer runs
Then the serialization with defaults excluded omits the entire `deployment` block
And omits any other block whose values match their defaults
And the resulting YAML contains only the business block (and any other non-default fields)
And re-loading the file via the project overlay loader rebuilds the same effective overlay
  because absent blocks reconstruct from default values
```

#### UC-CFG-WRITE-4: JSON-mode dump produces YAML-safe primitives

```
Given a project overlay that contains fields backed by non-native types (e.g., paths, enums)
When the JSON-mode serialization runs
Then path values are serialised as strings
And enum values are serialised as their string representation
And the resulting dict is composed entirely of JSON-native primitives (str, int, float, bool, list, dict, None)
And the YAML serializer accepts the dict without raising on unsupported types
```

#### UC-CFG-WRITE-5: Caller controls validation; save assumes input is valid

```
Given a caller passes a project overlay instance that has not been re-validated since mutation
When the project-config writer runs
Then the writer does NOT re-run overlay validation
And the instance is serialised as-is; the on-disk file reflects exactly the in-memory state
And the responsibility for invariants (e.g., stable-channel pinning) lies with the caller
  before invoking the writer
```

### Cross-context references

- Operator tooling that mutates project config (the TUI wizard,
  `telec config patch`, scripted setup) is expected to route project-level
  writes through this atomic helper. There is no equivalent atomic helper
  for global or per-person overlays today.
- The atomic-replace contract is one of the inputs into the `config`
  domain's `config.effective.updated` event (see
  `project/spec/domain/config.md`): a filesystem watcher that observes an
  atomic-replace inode change can rely on the new file being complete, not
  partially written.

## Allowed values

- `path`: any writable filesystem path; the helper does not constrain
  filename or directory.
- `config`: a validated project overlay instance. The writer does not re-validate; invariants are the caller's responsibility.

## Known caveats

- **No parent-directory creation.** The project-config writer assumes the parent
  directory of `path` already exists. If it does not, `open(tmp_path, "w")`
  raises `FileNotFoundError`. Callers that may target a fresh project must
  create the directory tree themselves.
- **No locking against concurrent writers.** Two concurrent
  project-config writer calls on the same path race in the tmp-file step:
  the second writer's `open` truncates the first writer's tmp file. The
  atomic-rename contract still guarantees the FINAL on-disk file is one
  complete write, but which writer's content wins depends on scheduling.
- **fsync covers data, not the directory entry.** v1 fsyncs the tmp file
  descriptor but does not fsync the containing directory. On a crash
  immediately after the atomic rename, some filesystems may lose the rename
  metadata even though the data blocks are durable. The v1 contract is
  "atomic from the application's perspective"; storage-stack durability
  beyond fsync of the file is the operator's filesystem choice.
- **The sibling tmp path replaces the entire extension.** A path like
  `teleclaude.yml` becomes `teleclaude.tmp`; a path with no extension
  becomes `<stem>.tmp`. Two project files with different extensions but
  the same stem would share a tmp path — relevant only if a project ever
  saved both `teleclaude.yml` and `teleclaude.yaml` side by side.
- **Cleanup itself can fail.** The cleanup path removes the temp file only
  if it's present; if the cleanup itself raises (rare, e.g., permission
  revoked mid-failure), that secondary exception shadows the original via
  Python's `__context__` chain.
- **No-op for identical content.** The helper always rewrites the file
  even when the dumped payload matches the current on-disk content; there
  is no diff-and-skip optimisation. The atomic-replace contract treats
  every call as a real write.

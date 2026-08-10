---
description: 'The `telec config get` / `patch` / `validate` operator surface over the machine `config.yml` — it resolves the same path the runtime loads, validates a patch against the typed schema before the write lands, and writes through the sanctioned atomic machine-config writer.'
visibility: 'public'
---

# Machine Config CLI Surface — Spec

## Required reads

- @docs/project/spec/feature/config/machine-config-load.md
- @docs/project/spec/feature/config/machine-config-write.md

## What it is

`telec config get`, `telec config patch`, and `telec config validate` are the
operator and agent front door to the machine `config.yml`. They are a read/edit
layer over the same file the machine-config loader consumes at process start —
never a parallel resolution of their own.

Three properties define the surface:

1. **One resolution, shared with the runtime.** The CLI resolves the machine
   config through the same resolver the loader uses. What `get` prints is what
   the running system loads, and what `patch` mutates is the file the running
   system will reload. The process working directory never selects the target.

2. **Schema-safe mutation.** A patch is merged in memory and built through the
   typed machine-config schema before anything is written. An invalid patch is
   refused with the schema's own error and the on-disk file is left byte-for-byte
   unchanged, so an invalid edit surfaces at the moment of editing rather than at
   the next daemon start.

3. **One write path.** The accepted patch is persisted through the machine-config
   writer and its atomic-replace guarantees; the CLI holds no second
   serialization or replace routine of its own.

`validate` reports the same typed build against the resolved machine config as
part of full-system validation, so `get`, `patch`, and `validate` agree on both
the file and the schema.

## Canonical fields

### Use cases

#### UC-CFG-CLI-1: `get` reads the machine config the runtime loads

```
Given the machine config at <RuntimeConfig.home>/config.yml sets workflow.runner to "autostart"
And an unrelated config.yml file exists in the current working directory setting workflow.runner to "manual"
When an operator runs `telec config get workflow` from that working directory
Then the reported workflow.runner is "autostart"
And the working-directory file is not read
```

#### UC-CFG-CLI-2: `get` names the file it read

```
Given an operator runs `telec config get` with or without paths
When the command prints the requested configuration
Then the absolute path of the machine config it read is reported alongside the values
```

#### UC-CFG-CLI-3: A schema-invalid patch is refused before the write

```
Given the machine config on disk is valid
And a patch sets deployment.channel to "stable" with an empty deployment.pinned_minor
When an operator runs `telec config patch` with that patch
Then the merged configuration is built through the typed machine-config schema
And the build fails with the stable-channel-requires-pinned_minor error
And that error is reported to the operator
And the command exits non-zero
And the machine config on disk is unchanged
```

#### UC-CFG-CLI-4: A valid patch is merged, validated, and written atomically

```
Given the machine config on disk is valid
And a patch sets a key the typed machine-config schema accepts
When an operator runs `telec config patch` with that patch
Then the patch is deep-merged over the raw machine config mapping
And the merged mapping is built through the typed machine-config schema without error
And only then is the merged mapping persisted through the machine-config writer
And the write satisfies the machine-config writer's atomic-replace contract
And the resulting configuration is reported to the operator
```

#### UC-CFG-CLI-5: `patch` targets the machine config, not the working directory

```
Given an unrelated config.yml file exists in the current working directory
When an operator runs `telec config patch` from that working directory
Then the machine config at <RuntimeConfig.home>/config.yml is the file mutated
And the working-directory file is left unchanged
```

#### UC-CFG-CLI-6: `validate` builds the resolved machine config through the schema

```
Given an operator runs `telec config validate`
When full-system validation runs
Then the machine config is loaded from the same resolved path `get` and `patch` use
And it is built through the typed machine-config schema
And a schema failure is reported as a failed `config.yml` validation area with the schema error
And the command exits non-zero when any validation area fails
```

## Known caveats

- `patch` validates the merged mapping the same way the loader does — including
  `${VAR}` expansion and the adjacent `experiments.yml` side-file — so a patch
  accepted here is one the next load accepts. A patch that only validates because
  an environment variable is currently set can still fail a later load in an
  environment where that variable is absent; the surface validates the
  configuration, not the environment it will run in.
- `patch` persists the raw YAML mapping, not the loaded aggregate, per the
  machine-config writer's raw-mapping-input constraint. Runtime-derived fields
  never enter the file.
- `patch` rewrites the whole file from the parsed mapping, so comments and the
  original formatting of `config.yml` do not survive a patch. An operator who
  keeps annotations in the machine config edits it directly or through the
  wizard rather than through `patch`.
- `patch` inherits the machine-config writer's caveats, including its lack of
  concurrent-writer exclusion: a patch racing another machine-config write still
  yields one complete file, but which write wins is scheduling-dependent.

## See Also

- docs/project/spec/domain/config.md
- docs/project/spec/feature/config/stable-channel-pinning-rule.md

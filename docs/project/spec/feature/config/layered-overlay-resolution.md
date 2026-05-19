---
id: project/spec/feature/config/layered-overlay-resolution
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Layered configuration resolution composing global, project, and per-person YAML sources into an AppConfig per workspace.
---

# Layered Overlay Resolution — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The user-facing configuration surface (`teleclaude.yml`) lives at three
independent locations: a global file in the user's home directory, a project
file at the repository root, and an optional per-person file under
`~/.teleclaude/people/<name>/`. For any caller working with a workspace, v1
composes an `AppConfig` that holds whichever of these three files exist for
that workspace, validated against their per-level Pydantic models. The
composition is side-by-side, not merged — consumers read the layer they care
about (e.g., `identity` reads the global `people` list, `context_selector`
reads project `business.domains`, hook routing reads per-person `creds`).
Workspace type drives which optional layer loads: a path under
`<base>/.teleclaude/people/<name>` loads the per-person file; any other
workspace path loads the project file; the global file is always loaded.

## Canonical fields

### Use cases

#### UC-CFG-OVERLAY-1: Project workspace composes global plus project

```
Given a workspace at /repos/my-project that is not under ~/.teleclaude/people
And ~/.teleclaude/teleclaude.yml exists with a global config
And /repos/my-project/teleclaude.yml exists with a project config
When a caller invokes load_app_config(Path("/repos/my-project"))
Then load_global_config() reads ~/.teleclaude/teleclaude.yml into a GlobalConfig
And load_project_config(/repos/my-project/teleclaude.yml) reads the file into a ProjectConfig
And the per-person layer is left as None
And the returned AppConfig holds global_=GlobalConfig, project=ProjectConfig, person=None
```

#### UC-CFG-OVERLAY-2: Person workspace composes global plus per-person

```
Given a workspace at ~/.teleclaude/people/alice
And ~/.teleclaude/teleclaude.yml exists with a global config
And ~/.teleclaude/people/alice/teleclaude.yml exists with a per-person config
When a caller invokes load_app_config(Path("~/.teleclaude/people/alice"))
Then _is_person_workspace returns True (workspace.parent.name == "people" AND workspace.parent.parent.name == ".teleclaude")
And load_person_config reads the file into a PersonConfig
And the project layer is left as None
And the returned AppConfig holds global_=GlobalConfig, project=None, person=PersonConfig
```

#### UC-CFG-OVERLAY-3: Missing optional layer yields default-constructed model

```
Given a workspace at /repos/empty-project
And /repos/empty-project/teleclaude.yml does NOT exist
When a caller invokes load_app_config(Path("/repos/empty-project"))
Then load_project_config is NOT called for that workspace
And AppConfig.project is None (not a default-constructed ProjectConfig)
```

#### UC-CFG-OVERLAY-4: Missing config file in load_config yields default model

```
Given load_config(path, ProjectConfig) is called
And path does not exist on disk
When load_config runs
Then it returns ProjectConfig() (a default-constructed instance)
And no exception is raised
```

#### UC-CFG-OVERLAY-5: YAML read failure surfaces as ValueError

```
Given load_config(path, model_class) is called
And path exists but yaml.safe_load raises (malformed YAML, IO failure, permission denied)
When load_config runs
Then the error is logged via logger.error
And load_config raises ValueError chained to the original exception
And the message names the path that failed
```

#### UC-CFG-OVERLAY-6: Empty YAML yields default model

```
Given load_config(path, model_class) is called
And path exists but yaml.safe_load returns None (empty file or `---`)
When load_config runs
Then the raw value is coerced to an empty dict
And model_class.model_validate({}) returns a default-constructed instance
And the result is returned without warning
```

### Implementation pointers (v1)

- `teleclaude/config/loader.py:38-61` — generic `load_config` (reads YAML, expands env vars, validates, warns on unknown keys)
- `teleclaude/config/loader.py:64-66` — `load_project_config`
- `teleclaude/config/loader.py:85-89` — `load_global_config` (defaults to `teleclaude.paths.GLOBAL_CONFIG_PATH`)
- `teleclaude/config/loader.py:92-94` — `load_person_config`
- `teleclaude/config/loader.py:97-99` — `_is_person_workspace` (path-shape detection)
- `teleclaude/config/loader.py:102-121` — `load_app_config` (composes AppConfig per workspace)
- `teleclaude/config/loader.py:124-132` — `validate_config` (level dispatcher used by `telec config validate`)
- `teleclaude/config/schema.py:428-434` — `AppConfig` frozen dataclass

### Cross-context references

- Consumed by `identity` (`teleclaude/core/identity.py`) — uses `load_global_config` + `load_person_config` to resolve principals from `people` and per-person `creds`.
- Consumed by `context_selector` (`teleclaude/context_selector.py`) — uses `load_project_config` to read `business.domains` for docs filtering.
- Consumed by `docs_index` (`teleclaude/docs_index.py`) — uses `load_project_config` for indexing scope.
- The v2 `config` bounded context (see `docs/project/spec/domain/config.md`) targets a true "effective configuration" merge with `person → project → global` precedence and a `config.effective.updated` event. v1 does NOT compute that merge and does NOT emit that event — consumers read the layer they need from `AppConfig`.

## Known caveats

- **No precedence merging in v1.** `AppConfig` holds the three layers as separate fields. The "person overrides project overrides global" semantics described in the v2 domain spec are a v2 target; in v1 each consumer chooses which layer to read.
- **Global config is always loaded, even for missing files.** `load_global_config` calls `load_config(GLOBAL_CONFIG_PATH, GlobalConfig)`; when the file is missing the result is a default-constructed `GlobalConfig()` (empty people list, empty subscriptions, etc.).
- **Person-workspace detection is purely path-based.** `_is_person_workspace` only checks that `workspace.parent.name == "people"` and `workspace.parent.parent.name == ".teleclaude"`. It does not verify the workspace name is a registered person; a path matching the shape but pointing at a non-person directory is still treated as a person workspace.
- **No filesystem watcher.** v1 reads the overlays on demand each time `load_app_config` is called; there is no event emitted when any overlay file changes. Long-lived consumers cache results at their own discretion.
- **`load_config` returns a default model on missing file, but `load_app_config` returns `None`.** Two different "absent" representations exist depending on entry point: the generic helper hands back an empty instance, the composer hands back `None`. Consumers must know which they are reading.
- **Read order is global → person/project.** Within `load_app_config`, the global file is read first; the workspace-specific file is read second (person or project depending on path shape). There is no opportunity for the workspace file to influence which global file loads.

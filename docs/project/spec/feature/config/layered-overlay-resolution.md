---
description: 'Layered configuration resolution composing global, project, and per-person YAML sources into a workspace-scoped app config aggregate.'
visibility: 'public'
---

# Layered Overlay Resolution — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The user-facing configuration surface (`teleclaude.yml`) lives at three
independent locations: a global file in the user's home directory, a project
file at the repository root, and an optional per-person file under
`~/.teleclaude/people/<slug>/`. For any caller working with a workspace, the
config bounded context composes an app config that holds whichever of these
three files exist for that workspace, each validated against its layer schema.
The composition is side-by-side, not merged — consumers read the layer they care
about (e.g., `identity` reads the global `people` list, `context_selector`
reads project `business.domains`, hook routing reads per-person `creds`).
<!-- planned-change:config-kind-declaration -->
Workspace type drives which optional layer loads: a path under
`<base>/.teleclaude/people/<slug>` loads the per-person file; any other
workspace path loads the project file; the global file is always loaded.
<!-- change:config-kind-declaration -->
Workspace kind drives which optional layer loads: a workspace whose
configuration file declares itself a person configuration loads the
per-person file; a workspace declaring a project configuration loads the
project file; the global file is always loaded.
<!-- /planned-change:config-kind-declaration -->

## Canonical fields

### Use cases

#### UC-CFG-OVERLAY-1: Project workspace composes global plus project

<!-- planned-change:config-kind-declaration -->
```
Given a workspace at /repos/my-project that is not under ~/.teleclaude/people
And ~/.teleclaude/teleclaude.yml exists with a global config
And /repos/my-project/teleclaude.yml exists with a project config
When the config loading API is invoked for the workspace path
Then the global overlay is read from ~/.teleclaude/teleclaude.yml
And the project overlay is read from /repos/my-project/teleclaude.yml
And the per-person layer is left as None
And the returned app config holds the global overlay, the project overlay, and no person overlay
```
<!-- change:config-kind-declaration -->
```
Given a workspace at /repos/my-project
And ~/.teleclaude/teleclaude.yml exists with a global config
And /repos/my-project/teleclaude.yml exists with a project config declaring itself a project configuration
When the config loading API is invoked for the workspace path
Then the global overlay is read from ~/.teleclaude/teleclaude.yml
And the project overlay is read from /repos/my-project/teleclaude.yml
And the per-person layer is left as None
And the returned app config holds the global overlay, the project overlay, and no person overlay
```
<!-- /planned-change:config-kind-declaration -->

#### UC-CFG-OVERLAY-2: Person workspace composes global plus per-person

<!-- planned-change:config-kind-declaration -->
```
Given a workspace at ~/.teleclaude/people/alice
And ~/.teleclaude/teleclaude.yml exists with a global config
And ~/.teleclaude/people/alice/teleclaude.yml exists with a per-person config
When the config loading API is invoked for the workspace path
Then the path is detected as a person workspace (parent is "people" under ".teleclaude")
And the per-person overlay is read from the workspace path
And the project layer is left as None
And the returned app config holds the global overlay, no project overlay, and the per-person overlay
```
<!-- change:config-kind-declaration -->
```
Given a workspace at ~/.teleclaude/people/alice
And ~/.teleclaude/teleclaude.yml exists with a global config
And ~/.teleclaude/people/alice/teleclaude.yml exists with a per-person config declaring itself a person configuration
When the config loading API is invoked for the workspace path
Then the file's declared kind identifies the workspace as a person workspace
And the per-person overlay is read from the workspace path
And the project layer is left as None
And the returned app config holds the global overlay, no project overlay, and the per-person overlay
```
<!-- /planned-change:config-kind-declaration -->

#### UC-CFG-OVERLAY-3: Missing optional layer yields None

```
Given a workspace at /repos/empty-project
And /repos/empty-project/teleclaude.yml does NOT exist
When the config loading API is invoked for the workspace path
Then the project overlay loader is NOT called for that workspace
And the returned app config's project field is None (not a default-constructed overlay)
```

#### UC-CFG-OVERLAY-4: Missing config file in overlay loader yields default instance

```
Given the config overlay loader is called for a path that does not exist on disk
When the loader runs
Then it returns a default-constructed overlay instance
And no exception is raised
```

#### UC-CFG-OVERLAY-5: YAML read failure surfaces as an error

```
Given the config overlay loader is called for an existing path
And the YAML parser raises (malformed YAML, IO failure, permission denied)
When the loader runs
Then the error is logged
And the loader raises a configuration error chained to the original exception
And the message names the path that failed
```

#### UC-CFG-OVERLAY-6: Empty YAML yields default overlay instance

```
Given the config overlay loader is called for an existing path
And the file is empty or contains only `---`
When the loader runs
Then the raw value is coerced to an empty dict
And the overlay schema returns a default-constructed instance
And the result is returned without warning
```

### Cross-context references

- Consumed by the identity bounded context to resolve principals from the
  global `people` list and per-person credentials.
- Consumed by the context-selector capability to read project
  `business.domains` for docs filtering.
- Consumed by the knowledge / docs-index bounded context for project-scoped
  indexing.
- The `config` bounded context (`project/spec/domain/config.md`) targets a
  true "effective configuration" merge with `person → project → global`
  precedence and a `config.effective.updated` event. The current resolver
  does not compute that merge and does not emit that event — consumers
  read the layer they need from the composed app config.

## Known caveats

- **No precedence merging in v1.** The app config holds the three layers as separate fields. The "person overrides project overrides global" semantics described in the v2 domain spec are a v2 target; in v1 each consumer chooses which layer to read.
- **Global config is always loaded, even for missing files.** The global overlay loader is always called; when the file is missing the result is a default-constructed global overlay (empty people list, empty subscriptions, etc.).
<!-- planned-change:config-kind-declaration -->
- **Person-workspace detection is purely path-based.** The workspace is detected as a person workspace by checking that its parent directory is named "people" inside ".teleclaude". It does not verify the workspace name is a registered person; a path matching the shape but pointing at a non-person directory is still treated as a person workspace.
<!-- change:config-kind-declaration -->
- **Person-workspace detection reads the file's declaration, not the path.** A workspace is a person workspace when its configuration file declares itself one (see `project/spec/feature/config/tier-declaration.md`). The declaration does not by itself verify the workspace belongs to a registered person.
<!-- /planned-change:config-kind-declaration -->
- **No filesystem watcher.** The config bounded context reads overlays on demand at each load call; there is no event emitted when any overlay file changes. Long-lived consumers cache results at their own discretion.
- **Two different "absent" representations exist.** The generic overlay loader returns a default instance for a missing file; the workspace composer returns None for a missing optional layer. Consumers must know which entry point they are calling.
<!-- planned-change:config-kind-declaration -->
- **Read order is global → person/project.** The global file is read first; the workspace-specific file is read second (person or project depending on path shape). There is no opportunity for the workspace file to influence which global file loads.
<!-- change:config-kind-declaration -->
- **Read order is global → person/project.** The global file is read first; the workspace-specific file is read second (person or project according to the file's declared kind). There is no opportunity for the workspace file to influence which global file loads.
<!-- /planned-change:config-kind-declaration -->

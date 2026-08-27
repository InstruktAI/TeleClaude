---
description: 'Layered configuration resolution composing global, project, and per-person YAML sources into an app config aggregate for a resolved context, with the declared tier driving which optional layer loads.'
visibility: 'public'
---

# Layered Overlay Resolution — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The user-facing configuration surface (`teleclaude.yml`) lives at three
independent locations: a global file in the user's home directory, a project
file at the project root, and an optional per-person file under
`~/.teleclaude/people/<slug>/`. For any caller with a resolved context, the
config bounded context composes an app config that holds whichever of these
three files exist for that context, each validated against its tier schema.
The composition is side-by-side, not merged — consumers read the layer they care
about (e.g., `identity` reads the global `people` list, `context_selector`
reads project `business.domains`, hook routing reads per-person `creds`).
The declared tier drives which optional layer loads: a context root whose
configuration file declares itself a person configuration loads the per-person
file; one declaring a project configuration loads the project file; the global
file is always loaded. The tier declaration itself is specified in
`project/spec/feature/config/tier-declaration.md`.

## Canonical fields

### Use cases

#### UC-CFG-OVERLAY-1: Project context composes global plus project

```
Given a context root at /repos/my-project
And ~/.teleclaude/teleclaude.yml exists with a global config
And /repos/my-project/teleclaude.yml exists with a project config declaring itself a project configuration
When the config loading API is invoked for that context root
Then the global overlay is read from ~/.teleclaude/teleclaude.yml
And the project overlay is read from /repos/my-project/teleclaude.yml
And the per-person layer is left as None
And the returned app config holds the global overlay, the project overlay, and no person overlay
```

#### UC-CFG-OVERLAY-2: Person context composes global plus per-person

```
Given a context root at ~/.teleclaude/people/alice
And ~/.teleclaude/teleclaude.yml exists with a global config
And ~/.teleclaude/people/alice/teleclaude.yml exists with a per-person config declaring itself a person configuration
When the config loading API is invoked for that context root
Then the file's declared tier identifies the person overlay
And the per-person overlay is read from that context root
And the project layer is left as None
And the returned app config holds the global overlay, no project overlay, and the per-person overlay
```

#### UC-CFG-OVERLAY-3: Missing optional layer yields None

```
Given a context root at /repos/empty-project
And /repos/empty-project/teleclaude.yml does NOT exist
When the config loading API is invoked for that context root
Then the project overlay loader is NOT called for that context
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
- Tier declarations and context-root resolution are specified in
  `project/spec/feature/config/tier-declaration.md`; this contract consumes
  the resolved context and its declared tier.
- The `config` bounded context (`project/spec/domain/config.md`) targets a
  true "effective configuration" merge with `person → project → global`
  precedence and a `config.effective.updated` event. The current resolver
  does not compute that merge and does not emit that event — consumers
  read the layer they need from the composed app config.

## Known caveats

- **No precedence merging in v1.** The app config holds the three layers as separate fields. The "person overrides project overrides global" semantics described in the v2 domain spec are a v2 target; in v1 each consumer chooses which layer to read.
- **Global config is always loaded, even for missing files.** The global overlay loader is always called; when the file is missing the result is a default-constructed global overlay (empty people list, empty subscriptions, etc.).
- **Person detection reads the file's declaration, not the path.** A context is a person context when its configuration file declares itself one (see `project/spec/feature/config/tier-declaration.md`). The declaration does not by itself verify the directory belongs to a registered person.
- **No filesystem watcher.** The config bounded context reads overlays on demand at each load call; there is no event emitted when any overlay file changes. Long-lived consumers cache results at their own discretion.
- **Two different "absent" representations exist.** The generic overlay loader returns a default instance for a missing file; the app-config composer returns None for a missing optional layer. Consumers must know which entry point they are calling.
- **Read order is global → person/project.** The global file is read first; the tier-specific file is read second (person or project according to the file's declared tier). There is no opportunity for the tier-specific file to influence which global file loads.

---
description: 'Layered configuration resolution composing global, project, and per-person YAML sources into an app config aggregate for a resolved context, with the declared tier driving which optional layer loads.'
visibility: 'public'
---

# Layered Overlay Resolution — Spec

## Required reads

- @docs/local/spec/domain/config.md

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
`local/projects/teleclaude/spec/feature/config/tier-declaration.md`.

A present empty overlay is loaded as that tier's schema defaults. An existing
overlay that cannot be read or parsed is logged and fails with a
path-naming configuration error that preserves the original cause; it is not
silently replaced by an empty overlay.

## Canonical fields

### Use cases

#### UC-CFG-OVERLAY-1: Project context composes global plus project

#### UC-CFG-OVERLAY-2: Person context composes global plus per-person

#### UC-CFG-OVERLAY-3: Missing optional layer yields None

#### UC-CFG-OVERLAY-4: Missing config file in overlay loader yields default instance

#### UC-CFG-OVERLAY-5: YAML read failure surfaces as an error

#### UC-CFG-OVERLAY-6: Empty YAML yields default overlay instance

### Cross-context references

- Consumed by the identity bounded context to resolve principals from the
  global `people` list and per-person credentials.
- Consumed by the context-selector capability to read project
  `business.domains` for docs filtering.
- Consumed by the knowledge / docs-index bounded context for project-scoped
  indexing.
- Tier declarations and context-root resolution are specified in
  `local/projects/teleclaude/spec/feature/config/tier-declaration.md`; this contract consumes
  the resolved context and its declared tier.
- The `config` bounded context (`local/projects/teleclaude/spec/domain/config.md`) targets a
  true "effective configuration" merge with `person → project → global`
  precedence and an effective-configuration-updated event. The current resolver
  does not compute that merge and does not emit that event — consumers
  read the layer they need from the composed app config.

## Known caveats

- **No precedence merging.** The app config holds the three layers as separate fields. The effective-configuration merge with "person overrides project overrides global" precedence belongs to the config domain spec's target state, not to this contract: each consumer chooses which layer to read.
- **Global config is always loaded, even for missing files.** The global overlay loader is always called; when the file is missing the result is a default-constructed global overlay (empty people list, empty subscriptions, etc.).
- **Person detection reads the file's declaration, not the path.** A context is a person context when its configuration file declares itself one (see `local/projects/teleclaude/spec/feature/config/tier-declaration.md`). The declaration does not by itself verify the directory belongs to a registered person.
- **No filesystem watcher.** The config bounded context reads overlays on demand at each load call; there is no event emitted when any overlay file changes. Long-lived consumers cache results at their own discretion.
- **Two different "absent" representations exist.** The generic overlay loader returns a default instance for a missing file; the app-config composer returns None for a missing optional layer. Consumers must know which entry point they are calling.
- **Read order is global → person/project.** The global file is read first; the tier-specific file is read second (person or project according to the file's declared tier). There is no opportunity for the tier-specific file to influence which global file loads.

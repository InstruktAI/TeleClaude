---
description: 'Every same-named configuration file (global, project, person, company) declares its own kind, and workspace resolution reads that declaration — the nearest declaration anchors the workspace; git topology only locates shared state.'
delivered_by:
  - config-kind-declaration
---

# Workspace Declaration — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every same-named configuration file states what it is: a kind declaration
inside the file identifies it as the global, project, person, or company
configuration, and an editor schema reference lets editors validate the file
as its declared kind. Meaning comes from the file, never from where it sits.
The company file participates in self-identification only — what a company
configuration composes and how it layers is unchanged by this contract.

Workspace resolution reads declarations instead of inferring from location:

- **Identity** — the nearest ancestor directory carrying a configuration
  declaration is the workspace root, and that file's declared kind is the
  workspace kind. No declaration among the ancestors means no workspace:
  read surfaces proceed with global-scope information only.
- **Shared state** (project workspaces only) — the git metadata at the
  workspace root decides where shared project state lives: a primary checkout
  owns its own state; a linked worktree's shared state lives at the owning
  checkout; a project workspace with no git checkout at its root fails loud.

A sanctioned one-time transition brings existing configuration files to the
declared state; afterwards loading is strict — a workspace configuration file
without a valid declaration is an error and is never loaded as another tier.

## Canonical fields

### Declaration shape

- Every same-named configuration file carries a `kind` field declaring which
  tier it is: `global`, `project`, `person`, or `company`. The machine
  configuration file is outside this contract — it carries a different
  filename and never participates in workspace-marker discovery.
- Every file references its published editor schema, so an editor validates
  the file as its declared kind. The schema files are published by this
  repository alongside the existing MCP-registry schema.
- The declaration is a declared, validated field of each layer's typed
  schema — never an unvalidated passenger key.

### Use cases

#### UC-CFG-WSD1: Declared kind governs, not location

```
Given a workspace root whose teleclaude.yml declares itself a person configuration
And the workspace directory does not sit under any conventional person-folder location
When an agent loads configuration for that workspace
Then the file is loaded as a person overlay
And the workspace is treated as a person workspace
```

#### UC-CFG-WSD2: Nearest declaration anchors subfolder invocation

```
Given a human or agent invokes the CLI from a subdirectory inside a workspace
When the workspace is resolved
Then the nearest ancestor directory carrying a configuration declaration is the workspace root
And that file's declared kind governs the workspace
```

#### UC-CFG-WSD3: A person workspace needs no git checkout

```
Given a person workspace whose configuration declares itself a person configuration
And no git checkout exists at or above the workspace root
When an agent invokes a read surface such as the docs index from within that workspace
Then the workspace resolves as a person workspace
And no failure about a missing project checkout occurs
```

#### UC-CFG-WSD4: Worktree shared state resolves to the owning checkout

```
Given a project workspace that is a linked git worktree of an owning checkout
When an agent resolves shared project state such as the todo store from within the worktree
Then the shared state root is the owning checkout, never the worktree itself
```

#### UC-CFG-WSD5: A project workspace without git fails loud on shared state

```
Given a workspace whose configuration declares itself a project configuration
And no git metadata exists at the workspace root
When shared project state is resolved for that workspace
Then resolution fails with a clear error naming the workspace root
```

#### UC-CFG-WSD6: The transition brings existing files to the declared state

```
Given existing same-named configuration files authored before kind declarations existed
When the operator runs the sanctioned transition
Then each of those files receives its correct kind declaration
And repeating the transition leaves already-declared files unchanged
```

#### UC-CFG-WSD7: Post-transition loading is strict

```
Given the sanctioned transition has completed
And a workspace configuration file carries no kind declaration
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
```

#### UC-CFG-WSD8: An invalid declaration never loads as another tier

```
Given a workspace configuration file whose declaration names an unknown or tier-inconsistent kind
When that file is loaded
Then loading fails with a clear error naming the file and the invalid declaration
And the file is never loaded as another configuration tier
```

#### UC-CFG-WSD9: A company configuration is recognized, never misclassified

```
Given a company configuration file declaring itself a company configuration
When workspace discovery encounters it
Then it is recognized as company configuration
And it is never treated as a workspace configuration of another tier
And company configuration composition behaves as it did before this contract
```

### Cross-context references

- The layered overlay composition this declaration dispatches is specified in
  `project/spec/feature/config/layered-overlay-resolution.md`; the declared
  kind replaces path-shape detection as the dispatch signal.
- Directories with no declaration ancestor keep the delivered global-only
  read behavior of the docs surfaces.

## Allowed values

- `kind`: `global`, `project`, `person`.

## Known caveats

- The declaration identifies what a configuration file is; it does not by
  itself verify that a person workspace belongs to a registered person.
  Identity verification is owned by the identity context and person-tier
  work.

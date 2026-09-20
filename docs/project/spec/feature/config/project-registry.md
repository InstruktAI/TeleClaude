---
description: The durable registry of project roots — which checkout is recorded for
  a project, who writes it, and which paths never write it.
visibility: internal
---

# Project Registry — Spec

## What it is

The project registry is the machine's durable list of adopted project roots. It
is what every consumer enumerates to answer "which projects exist here" —
<!-- planned-change:retire-docs-watcher -->
documentation publisher resolution, the valid-domain set, global skill
composition, configuration advancement, the docs watcher's watch set, and the
project catalog. Its shape and location are config's, stated in
<!-- change:retire-docs-watcher -->
documentation publisher resolution, the valid-domain set, global skill
composition, configuration advancement, and the project catalog. Its shape and
location are config's, stated in
<!-- /planned-change:retire-docs-watcher -->
`project/spec/teleclaude-config`.

Adoption is what writes it. A project is recorded when it is initialized or
onboarded, and by nothing else: no deployment or synchronization path adds,
removes, or rewrites an entry. Recording is idempotent, so adopting an
already-recorded project changes nothing.

The recorded path is always the project's durable main checkout. A project may
be adopted from inside a linked worktree, and the registry still names the
checkout that owns it, so an ephemeral worktree path is never enumerated as a
project.

## Canonical fields

- **Identity.** One entry per project, addressed by its durable main checkout.
- **Writer.** Adoption only. Idempotent, and never performed by a deployment or
  synchronization path.
- **Readers.** Every consumer that enumerates projects reads this registry
  rather than discovering projects from the filesystem.

### Use cases

#### UC-CFG-REG1: Adoption records a project's durable main checkout

```gherkin
Given a project whose linked worktree is checked out alongside its main checkout
When an agent adopts that project from inside the worktree
Then the registry lists the project once, by its main checkout
And the worktree is absent from the registry
And adopting it again leaves the registry unchanged
```

<!-- planned-change:retire-docs-watcher -->
#### UC-CFG-REG2: Synchronization never writes the registry

```gherkin
Given a project that is not recorded in the registry
And that project publishes a documentation domain
When an agent invokes a deploy-mode synchronization for that project
Then the registry still does not list that project
And the synchronization completes its own phases
```
<!-- change:retire-docs-watcher -->
#### UC-CFG-REG2: Publication never writes the registry

```gherkin
Given a project that is not recorded in the registry
And that project publishes a documentation domain
When recorded-commit maintenance publishes that project's committed source
Then the registry still does not list that project
And publication completes its own phases
```
<!-- /planned-change:retire-docs-watcher -->

## Known caveats

- A project cloned onto a machine and never adopted there is absent from the
  registry, so the consumers above do not enumerate it. Adoption is the act that
  makes a checkout a project on this machine.

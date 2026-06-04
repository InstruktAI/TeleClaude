---
id: 'project/spec/feature/context/mother-project-publishing-gate'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Only the Mother project may publish global agent items from agents/; non-mother projects must use .agents/.'
---

# Mother Project Publishing Gate — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

A two-point silent skip that restricts global agent item publishing
(skills, commands, agents under the TeleClaude repo's `agents/` tree) to a
single canonical project known as the **Mother project** — the TeleClaude
repository itself. Every other project that participates in the Context
bounded context may carry project-local items under `.agents/`. Non-mother
projects are NOT rejected for having files under their own `agents/`
directory — the pipeline simply does not look there. The Mother repo's
`agents/` tree is the only `agents/` content the pipeline ever traverses
for global publishing.

The Mother project is identified by filesystem path equality between the
resolved project root and the resolved canonical TeleClaude repo root. The
check is binary: either the project is the Mother or it is not. There is
no graduated trust or per-project ACL.

Defense in depth: the gate fires in two places — the distribution
pipeline's global-source collection, and the resource validation pass that
runs before any deploy. Both paths build their global agent-source list
only when the project is the Mother; otherwise the list stays empty and
the rest of the pipeline proceeds normally over `.agents/` only.

## Canonical fields

### Use cases

```
Scenario: Mother project publishes global agent items
  Given the project root equals the canonical TeleClaude repo root
  And the Mother project has files under agents/
  When the distribution pipeline computes the Mother-project gate
  Then the project is recognized as the Mother
  And global agent sources are populated from agents/
  And the items deploy to ~/.claude/, ~/.gemini/, and ~/.codex/
```

```
Scenario: Non-mother project's local agents/ is silently ignored
  Given the project root is not equal to the canonical TeleClaude repo root
  And the project contains files under its own agents/ directory
  When sync runs
  Then the project is not recognized as the Mother
  And the global agent-source list stays empty in both the distribution pipeline and the validator
  And the project's own agents/ tree is NOT traversed for global publishing
  And no error is raised about the local agents/ contents
  And only .agents/ is processed for project-local artifacts
```

```
Scenario: Non-mother project publishes project-local items
  Given the project root is not equal to the canonical TeleClaude repo root
  And the project contains files under its .agents/ directory
  When sync runs
  Then validation accepts the .agents/ contents
  And local items deploy to the project root (and ~/.teleclaude/commands for Codex)
  And no global publishing occurs
```

```
Scenario: Mother project with empty global artifact directories
  Given the project root equals the canonical TeleClaude repo root
  And the global agents/, commands/, and skills source directories are missing or empty
  When the distribution pipeline collects global sources
  Then the Mother source entry is preserved in the global-source list
  And later validation and build loops skip any missing source directory
  And no global artifact items are discovered from those missing directories
  And the pipeline proceeds without error
```

### Cross-context references

- **config** — supplies the project identity and the canonical TeleClaude
  repo root used for the path-equality check. Worktree checkouts resolve
  their canonical root via the canonical-root resolver.

## Known caveats

- Path equality is sensitive to checkout shape: symlinked copies or
  worktrees of the Mother project may or may not register as mother
  depending on how the path is resolved. Worktrees specifically read
  their canonical root via the canonical-root resolver so the gate
  recognises them correctly.
- The gate is binary. There is no concept of "trusted contributor
  projects" with partial global write rights. Either you are the Mother
  or you are not.
- The gate is silent skip, not reject. A non-mother project that
  accidentally creates an `agents/` directory will see those files
  ignored — sync emits no warning, validation reports no error.
  Operators relying on the gate to flag the mistake will not see it.
- Filesystem-isolation-dependent. A local actor with write access to the
  canonical Mother path is not prevented from impersonating the Mother
  project. The gate is a safety net against accident, not an attacker
  control.
- Missing global artifact directories on the Mother project are tolerated:
  the Mother source entry remains in the global-source list, but the
  missing subdirectories produce no artifact items rather than an error.

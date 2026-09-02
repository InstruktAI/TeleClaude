---
description: "Global agent artifacts publish only within a repository's declared reach: general commands, global skills, and global subagents are the mother's alone, domain commands belong to the domain's one publisher, and a source outside that reach is refused at sync."
visibility: 'public'
---

# Mother Project Publishing Gate — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

A reach gate on global agent-artifact publishing. Every repository carries the
same authored layout, `agents/{global,project}/{agents,commands,skills}`, and
the gate decides which of a repository's `agents/global/` sources it may
publish:

- General commands, global skills, and global subagents publish from the
  mother repository alone.
- Domain-partitioned commands (`agents/global/commands/<domain>/`) publish from
  the single repository that declares that domain in `business.publishes` —
  the same one-owner-per-domain rule that governs documentation domains.
- `agents/project/` is every repository's own and is never subject to the gate.

Reach follows declaration and ownership, never location or the identity of
the invoking checkout. The mother is identified as it is for documentation:
the resolved canonical TeleClaude repository root.

The gate refuses rather than skips. A source outside the repository's reach is
a validation finding that names the file and the reach it exceeds, and it
blocks the sync like any other validation finding. The gate fires in both the
pre-deploy validation pass and the distribution pipeline's source collection,
so an out-of-reach source can neither pass validation nor be built.

## Canonical fields

Side-project reach and the refusal of out-of-reach sources are bound by
`UC-ARD23` in `project/spec/feature/context/agent-runtime-deployment` and
`UC-AAV2` in `project/spec/feature/context/agent-artifact-validation`; this
spec references those scenarios rather than restating them.

### Use cases

#### UC-MPG1: The mother publishes every global artifact class

```gherkin
Scenario: The mother publishes general commands, global skills, and global subagents
  Given the project root equals the canonical TeleClaude repository root
  And it carries general commands, global skills, global subagents, and domain commands for domains it publishes under agents/global/
  When sync runs in deploy mode
  Then every one of those sources is validated and published to its global consumer
```

#### UC-MPG2: The mother with empty global directories publishes nothing and fails nothing

```gherkin
Scenario: Mother project with empty global artifact directories
  Given the project root equals the canonical TeleClaude repository root
  And the global agents, commands, and skills source directories are missing or empty
  When the distribution pipeline collects global sources
  Then no global artifact items are discovered from those directories
  And the pipeline proceeds without error
```

### Cross-context references

- **config** — supplies the project identity, the canonical TeleClaude
  repository root used for the mother check, and each repository's
  `business.publishes` declaration that bounds its domain reach.

## Known caveats

- Path equality is sensitive to checkout shape: worktrees of the mother
  resolve their canonical root through the canonical-root resolver so the gate
  recognises them.
- Reach is declared, not graduated. There is no trusted-contributor tier with
  partial global rights beyond a repository's own published domains.
- Filesystem-isolation-dependent. A local actor with write access to the
  canonical mother path is not prevented from impersonating the mother, and a
  repository can declare any domain nobody else publishes. The gate is a
  safety net against accident, not an attacker control.

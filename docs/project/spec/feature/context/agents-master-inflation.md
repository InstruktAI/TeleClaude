---
description: 'AGENTS.global.md (mother-project) and per-project AGENTS.master.md are inflated into deployed AGENTS files by recursively expanding @-refs.'
visibility: 'public'
---

# AGENTS.master Inflation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Inflation is the build-time step that turns hand-authored agent baseline
Sources — the platform-wide `AGENTS.global.md` (owned by the Mother project)
and each project's `AGENTS.master.md` — into self-contained Deployed `AGENTS.md`
files for every project. Inflation works by recursively expanding `@path.md`
inline references inside the source, so the Deployed artifact is one
self-contained document an agent CLI can read without resolving a tree of
refs at runtime.

Inflation runs as a Sync step. The Source authors hold the canonical content;
inflation produces the Deployed copies under each project root plus the
per-agent shim (`CLAUDE.md` points at `AGENTS.md`).

## Canonical fields

### Use cases

```
Scenario: Mother project sync inflates the global baseline
  Given the current process is running from the Mother project root
  And AGENTS.global.md exists at the Mother project root
  And AGENTS.global.md contains @-refs to baseline snippet files
  When the sync step inflates agent baselines
  Then the inflater recursively inlines every @-ref to a depth of at most 20
  And the resulting AGENTS.md is emitted at the Mother project root
  And a CLAUDE.md shim is emitted alongside it pointing at AGENTS.md
```

```
Scenario: Non-mother project skips the global source
  Given the current process is running from a non-mother project root
  And AGENTS.global.md does not apply to this project
  When the sync step inflates agent baselines
  Then AGENTS.global.md is not processed
  And only the project's own AGENTS.master.md is inflated
  And the project's AGENTS.md and CLAUDE.md shim are emitted under the project root
```

#### UC-AMI3: Progressive baseline expansion respects agent-output scope

<!-- planned-change:unify-baseline-progressive-sibling-convention -->

```
Scenario: Project progressive baselines omit the global activatable catalog
  Given a project AGENTS.master.md contains an @-ref to a baseline-progressive* file
  And the global documentation index contains activatable procedures
  When the inflater renders the project's AGENTS.md
  Then the ref is rendered as a progressive baseline index
  And the global "## Activatable Procedures" catalog is not included
  And procedure bodies are NOT inlined into the project's AGENTS.md
  And the progressive treatment is selected by filename prefix, not by target agent
```

<!-- change:unify-baseline-progressive-sibling-convention -->

```
Scenario: Each agent surface renders its progressive sibling by convention
  Given docs/project/baseline-progressive.md exists alongside docs/project/baseline.md
  And docs/global/baseline-progressive.md exists alongside docs/global/baseline.md at the Mother project root
  And no agent Source references either progressive file
  When the inflater renders the project's AGENTS.md and the global agent configuration
  Then each progressive sibling is detected by its location and rendered as a progressive baseline index
  And procedures carrying an activation_trigger are auto-included in their scope's "## Activatable Procedures" section with no manifest listing required
  And each activatable entry renders the procedure's description together with its activation trigger
  And the project's own activatable procedures render in a project-scoped "## Activatable Procedures" section
  And the global "## Activatable Procedures" catalog is not included in the project's AGENTS.md
  And the merged "## Activatable Procedures" catalog across all published domains is appended to the global agent configuration
  And @-ref expansion inlines every referenced snippet verbatim with no filename-based diversion
  And procedure bodies are NOT inlined into the project's AGENTS.md
```

<!-- /planned-change:unify-baseline-progressive-sibling-convention -->

<!-- planned:unify-baseline-progressive-sibling-convention -->

#### UC-AMI4: A hand-listed triggered procedure blocks the sync

```
Scenario: Hand-listed triggered procedure blocks the sync
  Given a baseline-progressive.md manifest listing a procedure snippet that carries an activation_trigger
  When the sync step inflates that scope's agent baseline
  Then the build fails with a validation error naming the manifest and the offending ref
  And the error directs removing the ref from the manifest
  And the failure is not downgradable to a warning
```

<!-- /planned:unify-baseline-progressive-sibling-convention -->

```
Scenario: Recursive ref expansion fails at the depth limit
  Given an @-ref tree whose expansion depth would exceed 20 levels
  When the inflater walks the tree
  Then expansion stops at depth 20
  And the build fails with a depth-limit error
  And no truncated AGENTS.md is emitted
```

```
Scenario: Idempotent re-inflation produces byte-identical output
  Given AGENTS.master.md and all referenced snippets are unchanged since the last sync
  When inflation runs again
  Then YAML frontmatter is dumped with stable key ordering
  And the Deployed AGENTS.md is byte-identical to the previous run
  And no spurious diff appears in the working tree
```

### Cross-context references

- **config** — Provides the project root list and the Mother project identity
  consulted at gating time.
- **agent_runtime** — Consumes the Deployed `AGENTS.md` (and `CLAUDE.md` shim)
  at agent CLI startup. The inflated file is the runtime baseline.

## Known caveats

<!-- planned-change:unify-baseline-progressive-sibling-convention -->

- The progressive-vs-full-inline rule is selected by **filename**, not by
  agent: any `@`-ref whose target filename starts with `baseline-progressive`
  is rendered as a progressive index for every agent. Non-progressive
  baseline refs are inlined fully for every target agent (Claude, Codex,
  Gemini). There is no Codex full-inline special case for progressive
  baselines.

<!-- change:unify-baseline-progressive-sibling-convention -->

- `baseline-progressive.md` is a **location convention**, never a reference
  target: it exists as a sibling of its `baseline.md` and is detected and
  appended by the inflater for each surface — domain bundle, project
  `AGENTS.md`, global agent config — through one shared collection and
  rendering path; only the scope of the activatable set differs per surface.
  No Source references it, and `@`-ref expansion inlines every referenced
  snippet verbatim for every target agent (Claude, Codex, Gemini) with no
  filename-based diversion.
- Manifests curate; frontmatter declares. The "Baseline index" renders the
  manifest's curated entries; the "Activatable Procedures" section is
  auto-collected from `activation_trigger` declarations in the scope's index.
  A triggered procedure hand-listed in a `baseline-progressive.md` manifest is
  dead weight — auto-inclusion already surfaces it — and sync flags it for
  removal from the manifest.

<!-- /planned-change:unify-baseline-progressive-sibling-convention -->

- The depth limit of 20 is a static constant in the inflater. A legitimately
  deeper ref tree would fail without a configuration knob — the fix is to
  flatten the ref tree at the Source, not to raise the limit.
- Mother-project gating is filesystem-path equality against the configured
  Mother root. There is no per-project ACL beyond "is this the Mother repo";
  any project whose root matches the configured path receives the global
  treatment.
- Source naming is asymmetric: the platform-wide Source is `AGENTS.global.md`,
  while the per-project Source is `AGENTS.master.md`. The asymmetry is
  intentional (different roles, different scopes) but easy to confuse with
  the Deployed `AGENTS.md` output.
- Embedded executable directives are resolved inline during expansion; this
  means the Deployed file can capture the output of a directive at sync time
  rather than at agent runtime.

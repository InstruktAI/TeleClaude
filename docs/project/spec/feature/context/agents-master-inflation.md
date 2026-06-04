---
id: 'project/spec/feature/context/agents-master-inflation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'AGENTS.global.md (mother-project) and per-project AGENTS.master.md are inflated into deployed AGENTS files by recursively expanding @-refs.'
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

```
Scenario: Progressive baseline refs always render as an index
  Given AGENTS.master.md contains an @-ref to a baseline-progressive* file
  When the inflater processes the ref
  Then the ref is rendered as a progressive index block listing activatable procedures
  And the procedure bodies are NOT inlined into the Deployed AGENTS.md
  And the same rendering applies for every target agent (Claude, Codex, Gemini)
  And the progressive treatment is selected by filename prefix, not by agent
```

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

- The progressive-vs-full-inline rule is selected by **filename**, not by
  agent: any `@`-ref whose target filename starts with `baseline-progressive`
  is rendered as a progressive index for every agent. Non-progressive
  baseline refs are inlined fully for every target agent (Claude, Codex,
  Gemini). There is no Codex full-inline special case for progressive
  baselines.
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

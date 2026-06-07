---
id: 'project/spec/feature/context/doc-snippet-three-phase-retrieval'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Three-phase doc retrieval: telec docs index lists IDs (phase 1), telec docs get returns content (phase 2), and Required-reads dependencies are surfaced for an explicit follow-up fetch (phase 3).'
---

# Doc Snippet Three-Phase Retrieval — Spec

## Required reads

- @docs/project/spec/domain/context.md
- @docs/project/spec/feature/context/doc-selection-policy.md

## What it is

The Index is exposed to agents and operators through a three-phase
retrieval flow:

1. **Phase 1 — discover.** `telec docs index` returns curated metadata
   (IDs, descriptions, and a ` (delivered by: …)` suffix for pending entries)
   so the caller can pick what to load.
2. **Phase 2 — fetch.** `telec docs get <id> [<id>...]` returns full
   content for the chosen IDs, with a `# Required reads (not loaded)`
   header listing dependency IDs the body referenced.
3. **Phase 3 — follow up explicitly.** Required reads are NEVER
   auto-loaded. To pull a dependency, the caller re-runs `telec docs
get` against the listed dependency IDs. The explicit follow-up keeps
   the caller in deliberate control of its context budget.

Role gating runs at phases 1 and 2 against the terminal session's
resolved identity; the same gate applies to any phase-3 follow-up fetch.

## Canonical fields

### Use cases

#### UC-3PR1: Phase-1 index renders delivered_by suffix for pending snippets

```
Given a logged-in operator with the default terminal role
When they run telec docs index --areas policy --domains software-development
Then phase 1 returns matching snippet metadata sorted by scope then ID
And each entry shows its ID and one-line description
And pending snippets (those with delivered_by) append " (delivered by: slug1,slug2)" to their line
And current snippets (no delivered_by) render with no suffix
```

```
Given a known snippet ID returned by phase 1
When the caller runs telec docs get <id>
Then full Source content is returned with frontmatter stripped
And a "# Required reads (not loaded)" header lists dependency IDs for explicit follow-up
And no Required reads are auto-fetched
```

```
Given an empty argument list
When the caller runs telec docs get
Then the command fails with "At least one snippet ID is required"
```

```
Given an unknown snippet ID
When the caller runs telec docs get unknown/id
Then the output includes "ERROR: Unknown snippet IDs: unknown/id"
And no content body is returned for that ID
```

```
Given a snippet whose visibility excludes the caller's role
When the caller runs telec docs get on that ID
Then the snippet is surfaced in the output with an "Insufficient role" / "access: denied" notice
And the content body is withheld
```

```
Given a third-party snippet ID
When the caller runs telec docs get on that ID
Then the content body is returned
And Required reads resolution is NOT applied to that ID
```

### Cross-context references

- **identity** — the terminal-session role is resolved against the active
  terminal login to determine which visibility tier the caller may see; that
  role drives gating in both phases.
- **selection** — both verbs delegate filter composition (areas, domains,
  baseline, target) to the Selection policy.

## Known caveats

- Required reads are NEVER auto-loaded. The caller must re-run `telec docs get`
  with the listed dependency IDs if they want the content. This is deliberate
  — the agent controls its context budget — but new agents routinely miss the
  follow-up step on first contact.
- Denied IDs are surfaced rather than hidden. An anonymous caller can confirm
  the existence of an `internal` snippet even though they cannot read it. This
  leaks identity information by design (so callers know to request a role
  lift) but is a real disclosure surface.
- Phase 1 third-party output ignores `--baseline-only` and `--target` filters
  entirely; third-party listings render on a separate track.
- The v1 CLI namespace is `telec docs *`. The v2 target is `telec context
docs *`. The verb rename is a known migration cleanup.

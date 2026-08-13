---
description: 'Three-phase doc retrieval: telec docs index lists IDs (phase 1), telec docs get returns content (phase 2), and Required-reads dependencies are surfaced for an explicit follow-up fetch (phase 3).'
visibility: 'public'
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
<!-- planned-change:required-reads-closure-guarantee -->
3. **Phase 3 — follow up explicitly.** Required reads are NEVER
   auto-loaded. To pull a dependency, the caller re-runs `telec docs
get` against the listed dependency IDs. The explicit follow-up keeps
   the caller in deliberate control of its context budget.
<!-- change:required-reads-closure-guarantee -->
3. **Phase 3 — follow up explicitly, or opt into the closure.** Required
   reads are never auto-loaded by default. To pull a dependency, the caller
   re-runs `telec docs get` against the listed dependency IDs — or passes
   `--closure` on the fetch itself to receive every body in the required-read
   closure in one pass, each snippet exactly once, with no pointer left to
   follow. The default keeps the caller in deliberate control of its context
   budget; the closure form is the caller's informed choice when the complete
   contract must reach context, at the cost of a larger response.
<!-- /planned-change:required-reads-closure-guarantee -->

Role gating runs at phases 1 and 2 against the terminal session's
resolved identity; the same gate applies to any phase-3 follow-up fetch.

## Canonical fields

### Use cases

#### UC-3PR1: Phase-1 index renders delivered_by suffix for pending snippets

```
Given a logged-in operator with the default terminal role
When they run telec docs index --areas policy --domains software-development
Then phase 1 returns matching snippet metadata sorted by taxonomy type general-to-specific (principle, concept, policy, procedure, design, spec, adr), then scope, then ID

And each entry shows its ID and one-line description
And pending snippets (those with delivered_by) append " (delivered by: slug1,slug2)" to their line
And current snippets (no delivered_by) render with no suffix
```

#### UC-3PR3: Phase-1 index --target lists a slug's pending work, new and reworked

```
Given a slug that delivers a not-yet-live new snippet (it appears in that snippet's delivered_by)
And the same slug reworks a live snippet via a planned section or companion (it appears in that snippet's superseded_by)
When an operator runs telec docs index --target <slug>
Then phase 1 lists the new snippet the slug delivers
And phase 1 also lists the live snippet the slug supersedes
And snippets that the slug neither delivers nor supersedes are omitted
```

#### UC-3PR2: Phase-2 get surfaces pending-change awareness for live parents

```
Given a snippet whose live parent carries a planned-change marker or companion
When the caller runs telec docs get <id>
Then the output renders the current contract body with pending material hidden
And a pending-changes awareness header names the owning slug
And the header tells the caller to inspect related files and read the snippet with --target <slug>
When the caller runs telec docs get <id> --target <slug>
Then the output renders that slug's pending view
And no pending-changes awareness header is appended
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

#### UC-3PR4: Unknown --project slug returns empty, not an error

```
Given a --project <slug> matching no project in the cross-project catalog
When the caller runs telec docs index --project <slug> (or telec docs get with the same flag)
Then no snippets match and the listing (or fetch) returns empty
And the command does not hard-fail — an unknown slug yields an empty result, not an error
```

```
Given a snippet whose visibility excludes the caller's role
When the caller runs telec docs get on that ID
Then the snippet is surfaced in the output with an "Insufficient role" / "access: denied" notice
And the content body is withheld
```

#### UC-3PR5: Unknown --domains value fails loud

```
Given a --domains value that names a domain outside the published-domain set
When the caller runs telec docs index --domains <value>
Then the command fails with a non-zero exit and an error naming the valid domains
And the listing is not silently returned unfiltered
```

#### UC-3PR6: Empty --domains value fails loud

```
Given a --domains value that supplies no domain (empty or comma-only)
When the caller runs telec docs index --domains <value>
Then the command fails with a non-zero exit as a missing value
And the listing is not silently returned unfiltered
```

```
Given a third-party snippet ID
When the caller runs telec docs get on that ID
Then the content body is returned
And Required reads resolution is NOT applied to that ID
```

<!-- planned:required-reads-closure-guarantee -->
#### UC-3PR7: Closure fetch loads the full required-read closure, deduplicated

```
Given a requested snippet whose required-read closure spans multiple dependency levels
And one dependency snippet is reachable through two different parents in that closure
When the caller runs telec docs get <id> --closure
Then the output renders the requested snippet body and the body of every snippet in the required-read closure
And the dependency reachable through two parents renders exactly once
And a "# Required reads (included)" header names the dependency IDs loaded beyond the requested set
And no "# Required reads (not loaded)" header is emitted
```

#### UC-3PR8: Default fetch names the closure form as the one-pass alternative

```
Given a requested snippet with required reads and no --closure flag
When the caller runs telec docs get <id>
Then the "# Required reads (not loaded)" header lists the dependency IDs
And a follow-up line names --closure as the one-pass way to load them all
And no dependency body is rendered
```
<!-- /planned:required-reads-closure-guarantee -->

### Cross-context references

- **identity** — the terminal-session role is resolved against the active
  terminal login to determine which visibility tier the caller may see; that
  role drives gating in both phases.
- **selection** — both verbs delegate filter composition (areas, domains,
  baseline, scope, project, target) to the Selection policy.

## Known caveats

<!-- planned-change:required-reads-closure-guarantee -->
- Required reads are NEVER auto-loaded. The caller must re-run `telec docs get`
  with the listed dependency IDs if they want the content. This is deliberate
  — the agent controls its context budget — but new agents routinely miss the
  follow-up step on first contact.
<!-- change:required-reads-closure-guarantee -->
- Required reads are never auto-loaded by default. The caller either re-runs
  `telec docs get` with the listed dependency IDs or passes `--closure` to load
  the full closure in one pass. The default is deliberate — the agent controls
  its context budget — but instructed follow-up decays into skimming and
  skipping, which is why procedure catalogs direct agents to the closure form.
- The closure form resolves taxonomy snippets only: third-party IDs stay outside
  Required-reads resolution, and a dependency whose visibility excludes the
  caller's role is omitted from the closure output exactly as it is omitted from
  the default header today.
<!-- /planned-change:required-reads-closure-guarantee -->
- Denied IDs are surfaced rather than hidden. An anonymous caller can confirm
  the existence of an `internal` snippet even though they cannot read it. This
  leaks identity information by design (so callers know to request a role
  lift) but is a real disclosure surface.
- Phase 1 third-party output ignores `--baseline-only` and `--target` (third-party
  renders on a separate track), but `--scope` and `--project` do apply to it:
  `--scope` keeps only third-party entries of that scope, and `--project <slug>`
  drops third-party entirely, since third-party indexes are loaded for the current
  project and global only and are never cross-project-loaded.
- The v1 CLI namespace is `telec docs *`. The v2 target is `telec context
docs *`. The verb rename is a known migration cleanup.

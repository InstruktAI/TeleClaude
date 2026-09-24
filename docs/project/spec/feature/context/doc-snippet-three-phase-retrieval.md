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
3. **Phase 3 — follow up explicitly.** Required reads are never auto-loaded
   by default. To pull a dependency, the caller re-runs `telec docs get`
   against the listed dependency IDs. Separately, the generated Activatable
   Procedures catalog supplies a hidden one-pass fetch instruction for a
   delivered procedure; that instruction returns the procedure's eligible
   transitive required-read closure exactly once. A scheduled agent job's
   startup instruction uses the same one-pass fetch for the procedure its
   declaration names. Ordinary retrieval keeps the caller in deliberate control
   of its context budget and never exposes or activates the hidden form.

<!-- planned-change:docs-tier-layering -->
Role gating runs at phases 1 and 2 against the terminal session's
resolved identity; the same gate applies to any phase-3 follow-up fetch.
<!-- change:docs-tier-layering -->
Read depth is resolved at phases 1 and 2 from the caller's resolved identity
and relationships, per the Selection policy; the same depth applies to any
phase-3 follow-up fetch.
<!-- /planned-change:docs-tier-layering -->

<!-- planned:cli-authorization-docs-via-daemon -->
Both verbs are served by the daemon for the caller it resolves. The command
line sends its identity signals, its selectors, and the directory it was
invoked from, and prints the answer; it resolves no caller and filters nothing
(`project/spec/identity-and-auth` §6). Every role may read documentation
(`project/design/cli-authorization-matrix`), so no caller is refused retrieval:
read depth alone decides what an answer contains.
<!-- /planned:cli-authorization-docs-via-daemon -->

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

<!-- planned-change:docs-tier-layering -->
```
Given a snippet whose visibility excludes the caller's role
When the caller runs telec docs get on that ID
Then the snippet is surfaced in the output with an "Insufficient role" / "access: denied" notice
And the content body is withheld
```
<!-- change:docs-tier-layering -->
#### UC-3PR11: A snippet the caller's depth does not admit is withheld

```
Given a snippet whose visibility the caller's resolved depth on its tier does not admit
When the caller runs telec docs get on that ID
Then the snippet is surfaced in the output with a withheld notice
And the content body is withheld
```
<!-- /planned-change:docs-tier-layering -->

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

#### UC-3PR7: Catalog activation loads the full eligible required-read closure, deduplicated

```
Given a delivered activatable procedure listed in a generated Activatable Procedures catalog
And its required-read closure spans multiple dependency levels
And one dependency snippet is reachable through two different parents in that closure
When an agent executes the fetch instruction shown by that catalog entry
Then the output renders the requested snippet body and the body of every snippet in the required-read closure
And the dependency reachable through two parents renders exactly once
And a "# Required reads (included)" header names the dependency IDs loaded beyond the requested set
And no "# Required reads (not loaded)" header is emitted
```

#### UC-3PR8: The hidden activation option appears only on its authorized surfaces

```
Given the CLI help, generated CLI documentation, baseline index instructions, default retrieval output, generated Activatable Procedures catalogs, and the job-runner startup instruction
When those surfaces are rendered
Then the hidden activation option appears in the telec docs get leaf-help Notes
And it appears in the generated Activatable Procedures catalog instruction
And it appears in the startup instruction a scheduled agent job receives for its procedure
But it is absent from CLI usage and option listings, generated CLI documentation, baseline index instructions, and default retrieval output
And using it with multiple requested IDs, a snippet that is not a procedure, a pending procedure, a third-party document, or a scope, project, or target filter fails before retrieval
```

#### UC-3PR9: Catalog activation distinguishes unreadable from ineligible closure members

```
Given a catalog-directed activatable-procedure fetch whose required-read graph contains an unreadable eligible dependency
When the fetch resolves the procedure's closure
Then the command exits non-zero with an error naming the unreadable dependency ID
And the "# Required reads (included)" header never names a dependency whose body was not rendered
And the output is never presented as a complete closure

Given the same fetch resolves a dependency that is pending for another delivery and therefore not part of the current contract
When the fetch resolves the procedure's closure
Then that dependency is omitted without a hard failure
And it is absent from the "# Required reads (included)" header
```

#### UC-3PR10: Documentation retrieval works outside a project checkout

```gherkin
Given an operator is working outside a registered project checkout
And one or more registered projects publish documentation
When they run telec docs index or telec docs get
Then documentation retrieval succeeds without requiring a current project
And the eligible global documentation and documentation published by registered projects are available
```

<!-- planned:cli-authorization-docs-via-daemon -->
#### UC-3PR12: An answer follows the identity the platform holds, not the one a caller claims

```gherkin
Given an agent session whose own process presents an identity claim different from the identity the platform holds for that session
And the claimed identity may read an internal snippet the held identity may not
When the session runs telec docs get on that snippet
Then the snippet is withheld with the access-denied notice
And the claim widens nothing the held identity could not already read
```

#### UC-3PR13: A caller the platform cannot identify receives the outsider's view

```gherkin
Given a caller that presents no identity the platform accepts
When the caller runs telec docs index or telec docs get
Then retrieval succeeds with material that declares itself public
And internal material is withheld
And a rejected credential yields the same answer as presenting none
```
<!-- /planned:cli-authorization-docs-via-daemon -->

### Cross-context references

<!-- planned-change:docs-tier-layering -->
- **identity** — the terminal-session role is resolved against the active
  terminal login to determine which visibility tier the caller may see; that
  role drives gating in both phases.
<!-- change:docs-tier-layering -->
- **identity** — the resolved caller: their person identity, platform role,
  and the company relationships and project reach resolution reports. Both
  verbs receive the resolved caller from the dispatch boundary and resolve
  nothing themselves; the Selection policy derives read depth from it.
<!-- /planned-change:docs-tier-layering -->
- **selection** — both verbs delegate filter composition (areas, domains,
  baseline, scope, project, target) to the Selection policy.

## Known caveats

- Required reads are never auto-loaded by default. The caller re-runs
  `telec docs get` with the listed dependency IDs. The default is deliberate:
  ordinary retrieval preserves the caller's context budget, while a generated
  Activatable Procedures catalog supplies the one-pass instruction only at the
  procedure-activation boundary where complete context is required.
- The one-pass activation form accepts exactly one delivered taxonomy
  procedure and does not compose with scope, project, or target filters. An
  activation trigger is not required: triggers mark procedures an agent may
  invoke on its own judgment, while a job procedure is executed by the runner. Third-party IDs stay outside Required-reads resolution; a dependency
  whose visibility excludes the caller's role or whose pending state excludes it
  from the current contract is absent from the included closure.
<!-- planned-change:docs-tier-layering -->
- Denied IDs are surfaced rather than hidden. An anonymous caller can confirm
  the existence of an `internal` snippet even though they cannot read it. This
  leaks identity information by design (so callers know to request a role
  lift) but is a real disclosure surface.
<!-- change:docs-tier-layering -->
- Withheld IDs are surfaced rather than hidden. A caller whose depth on a tier
  does not admit an `internal` snippet can still confirm that the identity
  exists. This is a deliberate disclosure surface for direct identities — the
  caller learns that a relationship to that tier would open it — and is
  confined to identities the caller names; the tier selectors disclose nothing.
<!-- /planned-change:docs-tier-layering -->
- Phase 1 third-party output ignores `--baseline-only` and `--target` (third-party
  renders on a separate track), but `--scope` and `--project` do apply to it:
  `--scope` keeps only third-party entries of that scope, and `--project <slug>`
  drops third-party entirely, since third-party indexes are loaded for the current
  project and global only and are never cross-project-loaded.
- The v1 CLI namespace is `telec docs *`. The v2 target is `telec context
docs *`. The verb rename is a known migration cleanup.


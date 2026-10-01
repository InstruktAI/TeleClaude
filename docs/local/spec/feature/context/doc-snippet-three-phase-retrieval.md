---
description: 'Three-phase doc retrieval: telec docs index lists IDs (phase 1), telec docs get returns content (phase 2), and Required-reads dependencies are surfaced for an explicit follow-up fetch (phase 3).'
visibility: 'public'
---

# Doc Snippet Three-Phase Retrieval — Spec

## Required reads

- @docs/local/spec/domain/context.md
- @docs/local/spec/feature/context/doc-selection-policy.md

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

Read depth is resolved at phases 1 and 2 from the caller's resolved identity
and relationships, per the Selection policy; the same depth applies to any
phase-3 follow-up fetch.

## Canonical fields

### Use cases

#### UC-3PR1: Phase-1 index renders delivered_by suffix for pending snippets

```
Given a logged-in operator with the default terminal role
When they run telec docs index --areas policy --domains sdlc
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
Given a --project <slug> naming no registered project
When the caller runs telec docs index --project <slug> (or telec docs get with the same flag)
Then no snippets match and the listing (or fetch) returns empty
And the command does not hard-fail — an unknown slug yields an empty result, not an error
```

#### UC-3PR11: A snippet the caller's depth does not admit is withheld

```
Given a snippet whose visibility the caller's resolved depth on its tier does not admit
When the caller runs telec docs get on that ID
Then the snippet is surfaced in the output with a withheld notice
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

#### UC-3PR10: Documentation retrieval works outside any home

```gherkin
Given an operator is working outside any project checkout, person home, or company home
When they run telec docs index without a selector
Then documentation retrieval succeeds without requiring a current home
And the listing holds their own person tier, the companies they belong to, and the eligible global documentation
And no other home's documentation is listed
```

<!-- planned-change:local-doc-ids-and-person-privacy -->
#### UC-3PR12: A home-qualified identity is retrieved from any location

```gherkin
Given a snippet ID projects/<slug>/<taxonomy>/<rest> of a registered project, or people/<slug>/… or companies/<slug>/… of a declared person or company
And the caller works in a different home or outside any home
When the caller runs telec docs get on that ID
Then the snippet is loaded from that home's catalog, whichever half holds it
And the caller's depth on that home decides whether its content or a withheld notice is returned
```
<!-- change:local-doc-ids-and-person-privacy -->
#### UC-3PR12: A home-qualified identity is retrieved from any location

```gherkin
Given a snippet ID local/projects/<slug>/<taxonomy>/<rest> of a registered project, people/<slug>/… or companies/<slug>/… of a declared person or company, or local/people/<slug>/… or local/companies/<slug>/… of one
And the caller works in a different home or outside any home
When the caller runs telec docs get on that ID
Then the snippet is loaded from the catalog of the half the identity names
And the caller's depth on that home decides whether its content or a withheld notice is returned
And a person's local identity is retrieved only by that person or a system principal
```
<!-- /planned-change:local-doc-ids-and-person-privacy -->

<!-- planned-change:local-doc-ids-and-person-privacy -->
#### UC-3PR13: An identity that names no home or domain is unknown

```gherkin
Given a snippet ID whose first segment is none of a published domain, general, a third-party root, or a home prefix
Or whose home prefix and slug name no registered project, declared person, or declared company
When the caller runs telec docs get on that ID
Then the output includes "ERROR: Unknown snippet IDs: <id>"
And no other home is searched for a similar identity
```
<!-- change:local-doc-ids-and-person-privacy -->
#### UC-3PR13: An identity that names no home or domain is unknown

```gherkin
Given a snippet ID whose first segment is none of local, a published domain, general, a third-party root, or a home prefix
Or whose home prefix and slug name no registered project, declared person, or declared company
Or that names a project home without the local/ prefix
When the caller runs telec docs get on that ID
Then the output includes "ERROR: Unknown snippet IDs: <id>"
And no other home is searched for a similar identity
```
<!-- /planned-change:local-doc-ids-and-person-privacy -->

<!-- planned-change:local-doc-ids-and-person-privacy -->
#### UC-3PR14: Naming a home lists it from any location

```gherkin
Given an operator working in one home or outside any home
When they run telec docs index naming another home by selector
Then the listing holds that home's published and local snippets at the depth their relationship grants
And nothing outside the named home is listed
```
<!-- change:local-doc-ids-and-person-privacy -->
#### UC-3PR14: Naming a home lists one of its halves from any location

```gherkin
Given an operator working in one home or outside any home
When they run telec docs index naming another home by selector
Then the listing holds that home's published snippets at the depth their relationship grants
When they run the same listing with --local
Then the listing holds that home's local snippets instead, at the same depth
And nothing outside the named home is listed
```

#### UC-3PR15: Retrieving another person's local identity is refused

```gherkin
Given a snippet ID local/people/<slug>/… naming a person other than the caller
And the caller is not a system principal, whatever its platform or company role
When the caller runs telec docs get on that ID, alone or with other IDs
Then the command exits non-zero with a refusal
And the refusal states that the owner's local documentation is private and names working in the owner's workspace as the way in
And no content body or withheld notice is returned
And the refusal is the same whether or not that person is declared
```
<!-- /planned-change:local-doc-ids-and-person-privacy -->

### Cross-context references

- **identity** — the resolved caller: a person with their platform role and the
  company relationships and project reach resolution reports, a system
  principal, or no identity. Both verbs obtain it once through identity's caller
  query at the command edge and resolve nothing further; the Selection policy
  derives read depth from it.
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
- Withheld IDs are surfaced rather than hidden. A caller whose depth on a tier
  does not admit an `internal` snippet can still confirm that the identity
  exists. This is a deliberate disclosure surface for direct identities — the
  caller learns that a relationship to that tier would open it — and is
<!-- planned-change:local-doc-ids-and-person-privacy -->
  confined to identities the caller names; the tier selectors disclose nothing.
<!-- change:local-doc-ids-and-person-privacy -->
  confined to identities the caller names; the tier selectors disclose nothing,
  and the refusal for another person's local half, which is the same whether or
  not that person is declared, discloses nothing either.
<!-- /planned-change:local-doc-ids-and-person-privacy -->
- Phase 1 third-party output ignores `--baseline-only` and `--target` (third-party
  renders on a separate track), but `--scope` and `--project` do apply to it:
  `--scope` keeps only third-party entries of that scope, and `--project <slug>`
  drops third-party entirely, since third-party indexes are loaded for the current
  project and global only and are never cross-project-loaded.
- The v1 CLI namespace is `telec docs *`. The v2 target is `telec context
docs *`. The verb rename is a known migration cleanup.

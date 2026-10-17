---
description: 'Pure-function curation of doc snippets by what the caller may see, taxonomy areas/domains, scope, baseline manifest anchoring, and target-slug filter.'
visibility: 'public'
---

# Doc Selection Policy — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Selection determines which documentation entries an index or identity
retrieval offers from the caller's eligible read set. Identity owns visibility
reach (`local/projects/teleclaude/spec/feature/identity/data-visibility`); the
selectors only narrow that set and never widen it. `--areas` filters by taxonomy,
`--domains` by published domain, and `--scope` by tier. `--project` selects the
named project's published material; `--baseline-only` keeps entries reachable
from the published-domain and project baseline manifests; `--target` includes
snippets delivered or reworked by the named slug; and `--local` selects the
selected or landed home's local half. Selectors compose by intersection, with
`--scope` adding no restriction alongside `--local`. Entries from multiple
companies remain separately addressable when their material covers the same
subject. Discovery names each participating person or company tier with its
contribution count, including an empty tier.

## Canonical fields

### Use cases

#### UC-DSP6: Without a relationship, the snippet's own declaration is the gate

#### UC-DSP20: A platform administrator reads every visibility

#### UC-DSP31: A caller acting as a system principal reads every visibility

#### UC-DSP7: An agent session with no resolvable identity receives the outsider's view

#### UC-DSP21: A local identity in the published tree is excluded

#### UC-DSP22: Areas filter keeps only the requested taxonomy

#### UC-DSP23: Without a domains filter every published domain stays visible

#### UC-DSP24: Baseline anchoring keeps only manifest-reachable identities

#### UC-DSP25: Target filter keeps only the named slug's snippets

#### UC-DSP19: Retrieving a discovered identity stays open to its discoverer

#### UC-DSP18: Reaching a tier by snippet identity meets the selector rule

#### UC-DSP1: Scope filter keeps only global snippets

#### UC-DSP2: Scope filter keeps only project snippets

#### UC-DSP3: Project filter keeps only the queried project's published snippets

#### UC-DSP4: Project filter on an unknown slug returns nothing

#### UC-DSP5: Domains filter keeps only snippets in the requested published domains

#### UC-DSP8: Read scope follows the caller, not the working directory

#### UC-DSP9: An agent session reads its own person tier in full

#### UC-DSP10: Belonging to a company opens that company's material in full

#### UC-DSP11: A project's owning company is read at the caller's own relationship

#### UC-DSP12: Assignment opens a project; company membership alone does not

#### UC-DSP26: A company's administrative role opens every project that company owns

#### UC-DSP13: A platform administrator reaches any named half but another person's local half

#### UC-DSP17: Naming a tier never widens a non-administrator's depth

#### UC-DSP29: Naming a related tier reads it in full

#### UC-DSP30: Discovery names every tier in the caller's read set, an empty one included

#### UC-DSP14: Membership in several companies stays unambiguous

#### UC-DSP15: Scope filter keeps only person snippets

#### UC-DSP16: Scope filter keeps only company snippets

#### UC-DSP34: Naming a person or company reads its published half from anywhere

#### UC-DSP35: Outside a person's local half, the half a snippet lives in never decides depth

#### UC-DSP36: The default read set carries both halves of the caller's own tiers

#### UC-DSP32: A company administrator reads their company's lineage in full

#### UC-DSP33: A company role below admin reads shared documentation at public-only depth

#### UC-DSP37: A help-desk session offers its desk's reach

#### UC-DSP38: The local selector reads a named home's local half

#### UC-DSP39: The local selector without a named home reads the landed home's local half

#### UC-DSP40: Only its owner and a system principal read a person's local half

#### UC-DSP41: A person reads their own local half in full

#### UC-DSP42: Another person's local half is left out of an unnamed read

#### UC-DSP43: A kind filter adds nothing next to the local selector

### Cross-context references

- **identity** — the resolved caller: a person with their platform role and
  the company relationships and project reach that resolution reports, a system
  principal, or no identity, received from the command edge, and the caller's
  visibility reach, which identity answers. Read depth is derived
  from these resolved answers; this policy owns neither the resolution nor the
  declarations beneath it.
- **config** — supplies the registered publishers' `business.publishes`
  declarations (their union is the valid-domain set), the project catalog that
  maps the slug of a `local/projects/<slug>/…` identity to its home, each person's
  and company's declaration that maps `people/<slug>` and `companies/<slug>`, with
  or without the `local/` prefix, to theirs, each project's own declaration of
  its owning company, and each tier's
  declared participation in the documentation surface. Declarations only; a
  caller's resolved relationships come from identity.

## Known caveats

- Snippet visibility defaults to `internal` when frontmatter omits the field.
  Public exposure is an explicit opt-in, not the default — so a freshly
  authored snippet without `visibility: public` is invisible to callers holding
  no relationship to its tier until the field is added. Callers who do hold a
  relationship read the tier in full and are unaffected by the default.
- Every published global domain is universally visible to every project; there
  is no per-project global-domain gate. The set of valid domains is the union of
  the registered publishers' `business.publishes`. The `--domains` flag still
  narrows a listing to requested domains on demand.
- Cross-project snippet `delivered_by` slugs are NOT normalized against the
  consuming project's todo list. A snippet that references a slug from a
  foreign project appears in the consuming project's index with a phantom
  dependency that no local lifecycle will ever resolve.
- Baseline manifest resolution matches snippets by `@`-ref file path; ID
  matching is secondary. Refactoring a snippet's filesystem path without
  updating the manifest silently drops it from the baseline set.

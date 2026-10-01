---
description: 'Pure-function curation of doc snippets by what the caller may see, taxonomy areas/domains, scope, baseline manifest anchoring, and target-slug filter.'
visibility: 'public'
---

# Doc Selection Policy — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

The Selection policy is the single pure-function composition point for every
filter that narrows the Index down to the snippets a caller actually wants.
Visibility, taxonomy areas, business domains, scope across the four tiers,
baseline-manifest anchoring, target-slug filtering, and the tier selectors all
flow through one place. Visibility is resolved against the caller's effective
role for each tier (`projects/teleclaude/design/architecture/scoped-roles`): an `admin`
effective role reads the tier in full; any other role reads its own company, its
reached projects, and its own person tier in full and the platform's shared
documentation at public-only depth; and where no role reaches a tier, the
snippet's own public-or-internal declaration is the only gate. Given the same Index and the
same inputs, the policy produces a byte-identical set of snippet IDs every
time. This determinism is what lets the retrieval flow be cached, replayed, and
reasoned about.

## Canonical fields

### Use cases

#### UC-DSP6: Without a relationship, the snippet's own declaration is the gate

```
Given an agent session running under the identity of a person who is not a platform administrator
And a tier that identity holds no declared relationship to
When the Selection policy resolves visibility for that tier
Then only snippets declaring themselves public are included
And snippets declaring themselves internal are excluded
```

#### UC-DSP20: A platform administrator reads every visibility

```
Given a caller holding the admin platform role
When the Selection policy resolves visibility
Then snippets of every visibility (public and internal) are included
```

#### UC-DSP31: A caller acting as a system principal reads every visibility

```
Given a caller acting as a system principal — a standing role, or a session one started
When the Selection policy resolves visibility
Then snippets of every visibility (public and internal) are included
```

#### UC-DSP7: An agent session with no resolvable identity receives the outsider's view

```
Given an agent session whose identity cannot be resolved
When the Selection policy resolves the read
Then no relationship-derived tier enters scope
And what the invocation itself offers is read at public-only depth
And the absent identity never widens the read
```

#### UC-DSP21: A local identity in the published tree is excluded

```
Given a snippet under ~/.teleclaude/docs/ whose ID begins local/
When the Selection policy filters the published tree
Then the snippet is excluded
And only domain-prefixed, people/<slug>/*, and companies/<slug>/* IDs survive
```

#### UC-DSP22: Areas filter keeps only the requested taxonomy

```
Given --areas policy passed by the caller
When the Selection policy applies the type filter
Then only snippets with frontmatter type: policy are returned
```

#### UC-DSP23: Without a domains filter every published domain stays visible

```
Given no --domains flag
When the Selection policy resolves the candidate set
Then every global snippet stays universally visible and the snippets of every home in the read set are included
And the valid domain set is the union of registered publishers' business.publishes
```

#### UC-DSP24: Baseline anchoring keeps only manifest-reachable identities

```
Given --baseline-only is set
When the Selection policy applies baseline anchoring
Then it loads every published domain's baseline.md manifest, general included, and the project's own manifest
And it keeps only IDs reachable via @-refs from the loaded manifests
And --domains then narrows that set to snippets in the requested domains
```

#### UC-DSP25: Target filter keeps only the named slug's snippets

```
Given --target <slug> is set
When the Selection policy applies the target filter
Then only snippets whose delivered_by includes <slug> are returned
And third-party snippets are silenced
```

#### UC-DSP19: Retrieving a discovered identity stays open to its discoverer

```
Given an agent session running under the identity of a person who is not a platform administrator
And discovery has returned an identity from a tier that session is permitted to read
When the session retrieves that identity
Then the snippet content is returned
And no tier authorization is required
```

#### UC-DSP18: Reaching a tier by snippet identity meets the selector rule

```
Given a snippet ID whose prefix names a home the caller's assembled catalogs do not contain — people/<slug> or companies/<slug> for a published snippet, local/projects/<slug>, local/people/<slug> or local/companies/<slug> for a local one
When the caller references that ID without a selector, from any location
Then the catalog of the half the identity names is loaded
And visibility gating applies at the depth the caller's relationship to that home grants
And a person's local half admits only that person and a system principal
```

#### UC-DSP1: Scope filter keeps only global snippets

```
Given --scope global passed by the caller
When the Selection policy applies the scope filter
Then only snippets with scope global are returned
And project-scoped snippets are excluded
```

#### UC-DSP2: Scope filter keeps only project snippets

```
Given --scope project passed by the caller
When the Selection policy applies the scope filter
Then only snippets in the project tier are returned — local project snippets, IDs beginning local/projects/<slug>/
And snippets of every other tier, published domain snippets included, are excluded
And combined with --project <slug>, whose published half holds only domain snippets, nothing is returned
And combined with --local, the filter adds nothing
```

#### UC-DSP3: Project filter keeps only the queried project's published snippets

```
Given --project <slug> naming a registered project
And the invocation runs in any location, inside that project or not
When the Selection policy applies the project filter
Then the published snippets of the domains that project publishes as owner are returned
And that project's local snippets are not returned
And snippets owned by any other home or domain publisher are excluded
And the filter composes with --areas, --domains, --baseline-only, --scope, --local, and --target
```

#### UC-DSP4: Project filter on an unknown slug returns nothing

```
Given --project <slug> naming no registered project
When the Selection policy applies the project filter
Then no snippets are returned
```

#### UC-DSP5: Domains filter keeps only snippets in the requested published domains

```
Given --domains <domain> passed by the caller
When the Selection policy applies the domains filter
Then only snippets whose domain is in the requested set are returned
And snippets carrying a structural marker — project, person, or company — are excluded
And general is a published domain the filter keeps when requested, like any other
And third-party entries are silenced
```

#### UC-DSP8: Read scope follows the caller, not the working directory

```
Given an agent session invoking documentation discovery from two different directories under one resolved identity
When the Selection policy resolves what that identity is permitted to see
Then the permitted set is identical in both invocations
And the working directory determines only which home's material is offered by default
```

#### UC-DSP9: An agent session reads its own person tier in full

```
Given an agent session whose identity resolves to a registered person
When the Selection policy resolves the read
Then that person's own tier is included in full without the session naming it
And no declaration on those snippets withholds them from their owner
```

#### UC-DSP10: Belonging to a company opens that company's material in full

```
Given an agent session running under the identity of a person holding a declared relationship to a company
When the Selection policy resolves that company's tier
Then every snippet of that company is included regardless of its own visibility declaration
And the role that person holds in that company does not change what is included
```

#### UC-DSP11: A project's owning company is read at the caller's own relationship

```
Given an agent session working in a project that declares an owning company
And the session's identity holds no declared relationship to that company
When the Selection policy resolves that company's tier
Then only snippets declaring themselves public are included
And the project's declaration of its owner still brings that company's tier into scope
```

#### UC-DSP12: Assignment opens a project; company membership alone does not

```
Given an agent session running under the identity of a person whose relationship to a company covers none of that company's projects
And that company owns several projects
And that person holds a declared relationship to one of them
When the Selection policy resolves that person's depth on those projects
Then the related project is read in full when the session works in it or names it
And the company's other projects are read at what they declare public
And no reached project enters the default read set on the relationship's account
```

#### UC-DSP26: A company's administrative role opens every project that company owns

```
Given an agent session running under the identity of a person holding a company's administrative role
And that company owns a project the person holds no explicit assignment to
When the Selection policy resolves that person's depth on that project
Then the project is read in full when the session works in it or names it
And a project owned by a different company gains no depth on that role's account
And the Selection policy reads the covered set as the roster resolves it rather than deriving it from the role
```

#### UC-DSP13: A platform administrator reaches any named half but another person's local half

```
Given an agent session running under the identity of a platform administrator
And the session names a person's published half, or a company's or a project's published or local half, explicitly
When the Selection policy resolves the request
Then that named half is returned in full
```

#### UC-DSP17: Naming a tier never widens a non-administrator's depth

```
Given an agent session running under the identity of a person who is not a platform administrator
And the session names a person, a company, or a project tier explicitly by selector
And that identity holds no declared relationship to the named tier
When the Selection policy resolves the request
Then only snippets of that tier declaring themselves public are returned
And the answer is identical whether the tier holds no public material or does not exist
```

#### UC-DSP29: Naming a related tier reads it in full

```
Given an agent session running under the identity of a person who is not a platform administrator
And the session names a company the person belongs to, a project the person reaches, or the person's own tier
When the Selection policy resolves the request
Then that named tier is returned in full
And no other tier is returned
```

#### UC-DSP30: Discovery names every tier in the caller's read set, an empty one included

```
Given an agent session whose read set contains a participating person or company tier that holds no snippets
When the session runs documentation discovery
Then the discovery output names each tier in the read set with the number of entries it contributes
And the empty participating tier is named with zero entries
And a tier outside the caller's read set is not named
```

#### UC-DSP14: Membership in several companies stays unambiguous

```
Given an agent session running under the identity of a person holding declared relationships to more than one company
And two of those companies publish material on the same subject
When the Selection policy resolves the read
Then each company's material remains separately addressable
And neither company's material shadows or displaces the other's
```

#### UC-DSP15: Scope filter keeps only person snippets

```
Given an agent session passing --scope person
When the Selection policy applies the scope filter
Then only snippets in the person tier are returned
And snippets of every other tier are excluded
```

#### UC-DSP16: Scope filter keeps only company snippets

```
Given an agent session passing --scope company
When the Selection policy applies the scope filter
Then only snippets in the company tier are returned
And snippets of every other tier are excluded
```

#### UC-DSP34: Naming a person or company reads its published half from anywhere

```
Given an agent session in any location
And the session names a person or a company by selector, without --local
When the Selection policy resolves the request
Then that home's published material is returned at the depth the caller's relationship to that home grants
And that home's local snippets are not returned
And no other home is returned
```

#### UC-DSP35: Outside a person's local half, the half a snippet lives in never decides depth

```
Given a company home holding an internal snippet in docs/global and a public snippet in docs/local
And a caller who holds no relationship to that home
When the caller names the company's local half, and separately its published half
Then the public docs/local snippet is included in the local listing
And the internal docs/global snippet is excluded from the published listing
```

#### UC-DSP36: The default read set carries both halves of the caller's own tiers

```
Given an agent session whose identity resolves to a person who belongs to a company
And both the person's home and the company's home hold snippets in docs/global and docs/local
When the session runs documentation discovery without a selector, from any location
Then the snippets of both halves of the person's home are included
And the snippets of both halves of the company's home are included
```

#### UC-DSP32: A company administrator reads their company's lineage in full

```
Given an agent session running under the identity of a person holding no platform role and the admin role in one company
When the Selection policy resolves visibility
Then internal snippets of that company's tier, of every project that company owns, and of the platform's shared documentation are included
And a project owned by another company is read only at public-only depth
```

#### UC-DSP33: A company role below admin reads shared documentation at public-only depth

```
Given an agent session running under the identity of a person holding no platform role and the member role in one company
When the Selection policy resolves visibility
Then internal snippets of that company's tier and of the projects the person is assigned to are included
And only public snippets of the platform's shared documentation are included
```

#### UC-DSP37: A help-desk session offers its desk's reach

```
Given a help-desk session whose visitor holds no relationship to the desk's home
When the session runs documentation discovery without a selector
Then a project desk offers that project's public snippets
And a company desk offers the public snippets of that company and of every project it owns
And both offer the public snippets of the platform's shared documentation, the help-desk documentation among them
And no internal snippet of an offered home the visitor holds no relationship to is included
And the visitor's own tiers are read at the depth their relationships grant
```

#### UC-DSP38: The local selector reads a named home's local half

```
Given an agent session in any location
And the session names a person, a company, or a project by selector together with --local
When the Selection policy resolves the request
Then that home's local snippets are returned at the depth the caller's relationship to that home grants
And that home's published snippets are not returned
And no other home is returned
```

#### UC-DSP39: The local selector without a named home reads the landed home's local half

```
Given an invocation landed in a project or a person home
When the session runs discovery with --local and no home selector
Then the landed home's local snippets are returned at the caller's depth
And no other home is returned
Given an invocation landed in no home
When the session runs discovery with --local and no home selector
Then the command is refused and the refusal names the selectors that name a home
```

#### UC-DSP40: Only its owner and a system principal read a person's local half

```
Given an agent session whose caller does not carry a person's identity and is not a system principal, whatever its platform or company role
When the session names that person's local half by --local --person <slug>
Then the command exits non-zero with a refusal
And the refusal states that the owner's local documentation is private and names working in the owner's workspace as the way in
And nothing is listed
And the refusal is the same whether or not that person is declared
```

#### UC-DSP41: A person reads their own local half in full

```
Given an agent session carrying a person's identity, or a system principal
When the session names that person's local half
Then every snippet of it is returned, whatever its visibility
```

#### UC-DSP42: Another person's local half is left out of an unnamed read

```
Given an invocation landed in a person's home
And its caller is neither that person nor a system principal
When the session runs discovery without a selector
Then that person's published snippets are returned at the caller's depth
And no snippet of that person's local half is returned
And the command is not refused
```

#### UC-DSP43: A kind filter adds nothing next to the local selector

```
Given an agent session passing --local, with or without a home selector
When it also passes --scope <kind>
Then the result is identical to the same request without --scope
```

### Cross-context references

- **identity** — the resolved caller: a person with their platform role and
  the company relationships and project reach that resolution reports, a system
  principal, or no identity, received from the command edge, and the person's
  effective role for each tier, which identity answers. Read depth is derived
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

---
description: Vendor-shaped runtime and model material is a built-in catalog with its own contract, outside the tiered machine-settings schema, which holds only closed-vocabulary knobs and references into that catalog.
visibility: internal
date: 2026-08-20
number: 77
---

# Runtime Catalog Is Separate From Machine Settings — ADR

## Context

The machine settings aggregate modelled agent runtimes as a mapping from agent
name to a structured runtime configuration, held inside the same tiered schema
that governs every other machine setting. Field tiers are the declared single
authority for what an operator may edit, and the mapping carried a public tier.

The schema walk that turns those tiers into a generated sample treats a container
of structured members as one opaque leaf — it does not descend into a mapping or a
list. Every field of the runtime configuration therefore inherited a public tier
that nothing generated, reconciled, or enforced. The observable consequence was
that an operator-declared launch profile parsed, passed validation, and was
discarded without a word, while the loader rebuilt the entry from built-in
constants and consumed two keys of the several the schema advertised.

Closing the gap from inside the settings model was attempted three ways, and each
grew the schema faster than it grew the surface. Descending into a dynamic mapping
requires wildcard path expansion through the reconciler and a per-instance
defaults shape that does not exist. Keying the mapping by the agent enum closes
the key vocabulary and makes members reachable, but leaves an entire vendor launch
contract — binaries, flag strings, session paths, transcript patterns, resume
grammars — inside the document whose purpose is operator settings. Declaring the
container ungoverned is honest but leaves the tiers asserting an operator surface
that does not exist.

The recurring shape across all three is that the material in question is not
settings. It is vendor description: what a harness is and how it is driven.

Prior art was consulted in the pi agent toolkit (earendil-works/pi), which keeps
typed application settings and a provider/model catalog as two documents with two
contracts, settings referring to catalog entries by identifier.

## Decision

Vendor-shaped material is a catalog, not settings, and lives outside the settings
schema with its own contract and its own loader. A catalog entry describes what a
runtime is and how it is driven: launch composition, permission postures, session
persistence, transcript shape, hook vocabulary, and the models it can select with
the parameters that select them.

Machine settings hold no vendor structure. They hold closed-vocabulary knobs and
references by identifier into the catalog: which runtimes are enabled, which is
the default, and the routing preferences that name runtimes and models in order
for a given unit of work.

An operator overlays the catalog through a separate document whose additions and
overrides are distinct keys, so introducing an entry cannot silently reshape a
built-in one.

The abstraction an operator reasons in stays in settings; its vendor-specific
realization stays in the catalog beside the runtime that needs it.

## Consequences

The settings schema holds no container of structured members for runtimes, so the
tier walk governs every leaf the tiers declare, and the generated sample can
express the operator surface without a per-instance projection.

An operator changing what a runtime launches selects a declared variant by name
rather than supplying a flag fragment that reaches the executed command. The
permission posture applied to non-admin sessions is built-in data, so widening it
is a reviewed change to shipped material rather than a line in a machine file.

Routing preferences — which runtimes and which models, in what order, for a given
unit of work — become typed lists of references, expressible in settings for the
first time.

Introducing a runtime is largely a catalog entry. What cannot be data stays code:
transcript iteration and hook adaptation are behavior, not description.

Two documents must agree. A settings reference naming an absent catalog entry is
a load-time error, not a silent fallback, and existing machine configurations
require migration to the split shape.

A runtime whose binary or credentials are absent is loaded and reported
unavailable rather than failing the load, so an incomplete environment degrades to
a visible state instead of an enabled entry that fails at launch.

## Alternatives Considered

**Teach the schema walk to descend into containers of structured members.**
Governs the members, and requires wildcard path expansion through the reconciler
plus a per-instance defaults shape. It leaves the vendor launch contract inside
the settings document, so every future harness enlarges the settings schema with
material no operator edits.

**Key the mapping by the agent enum and govern its members.** Closes the key
vocabulary, which is a real defect on its own terms, and makes members statically
reachable. It carries the same objection: the settings schema continues to hold
vendor description, and the operator surface grows by schema change rather than by
catalog entry.

**Declare the container ungoverned and leave it.** Accurate about the gap and
cheap, but the tiers continue to claim an operator surface nothing enforces, and
the questions that motivated the work — selecting a launch variant, ordering
runtimes and models per unit of work — remain unexpressible.

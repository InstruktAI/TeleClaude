---
visibility: public
number: 0059
date: 2026-06-25
description: Domains are published by the side projects that own them and surfaced to every project as universal one-line awareness with on-demand depth; the per-project subscriber model is dropped.
---

# Domain Publication and Universal Awareness — ADR

## Context

Global documentation snippets are served from `~/.teleclaude/docs`, a single whole-tree
symlink to the mother repo's `docs/global`. Only the mother project assembles global
sources, so a global snippet can physically live in exactly one repo, and the set of valid
domains is a hardcoded constant there. A project declares `business.domains` to "subscribe"
to domains — but that subscription only filters the `telec docs index` browse listing:
explicit `telec docs get <id>` resolves any snippet regardless, and the generated entrypoint
blocks already surface every domain unfiltered. Subscription gates discovery noise, not
capability.

Two forces made this untenable. Vendor- or application-coupled domains (an ERP integration
tied to a specific product, for example) had no home but the mother repo, coupling the
platform to vendor choices it should stay agnostic to. And the subscriber model carried the
conceptual weight of an access boundary while enforcing none — a gate that looked
load-bearing and was not.

## Decision

Domain knowledge is **published by the side projects that own it** and surfaced to every
project as **universal awareness with on-demand depth**:

- **Publisher-owned domains.** Any registered project may publish global snippets for a
  domain it owns. The global docs root is composed from every publisher's `docs/global`
  (multi-root resolution) rather than a single symlink to the mother repo. A domain has one
  owning publisher. The set of valid domains is derived from what publishers declare, not
  from a constant in the mother repo.
- **The mother repo is domain-agnostic.** It owns no vendor- or application-coupled domain;
  such domains live in their own side projects.
- **Universal awareness, on-demand depth.** Every project's entrypoint carries a generated
  one-line index per published domain — name, snippet count, and the path to that domain's
  baseline bundle. Depth is loaded on demand by reading the bundle, then reading individual
  snippets progressively. Awareness is cheap and universal; loading is scoped to the moment
  of need.
- **No subscriber gating.** The per-project subscriber model is dropped as a capability
  boundary. At most a cosmetic default scope for browse listings remains.

## Consequences

- A side project owns and publishes a domain — its docs and the tooling that operates it —
  with no presence in the mother repo, which stays vendor-neutral.
- Any agent in any project discovers any published domain and loads it on demand; no project
  needs special provisioning to become aware of a domain's existence.
- Domain validity is dynamic: publishing a new domain makes it visible everywhere with no
  mother-repo edit.
- Global snippet ownership is enforced across publishers (one owner per domain), replacing
  the single-repo collision check.
- The cheap-awareness / on-demand-depth split means a focused project carries one line per
  foreign domain as ambient surface — accepted as the price of universal discoverability.

## See Also

- ~/.teleclaude/docs/general/policy/context-retrieval.md
- ~/.teleclaude/docs/general/concept/documentation-snippets.md

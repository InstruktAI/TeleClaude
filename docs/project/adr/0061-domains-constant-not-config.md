---
visibility: public
number: 0061
date: 2026-06-26
description: Domain validity is a fixed platform-owned constant and publication is expressed by docs/global/<domain>/ folder presence; the dynamic publish-union validity and the business.domains/publishes config fields are removed.
---

# Domains Constant, Not Config — ADR

## Context

ADR-0059 made the set of valid domains **dynamic** — derived at runtime from the
union of every registered project's `business.publishes` declarations
(`teleclaude/domains.py::valid_domains`). That derivation is circular: the
validator computes its own allowlist from the very declarations it gates. It is
also bootstrap-fragile — the first publisher of a domain is unrecognized until
its declaration lands at a registered repo-root config, which produced a
169-reference `invalid_scope` outage when a domain's first publisher was
integrated.

The config surface restated facts the system already owns. Validity is a fixed
platform fact, not a per-project declaration. Publication is already expressed by
convention — a snippet under `docs/global/<domain>/` is published; `docs/project/`
is scoped. And `business.domains` (a domain→docs-path map) carried no information:
every registered config maps every domain to the literal `docs`, and a publisher
that omits a domain it publishes still publishes it (erpnext-ops publishes `erp`
with no `erp` entry in `business.domains`).

## Decision

Domain **validity** is a single platform-owned closed vocabulary, and
**publication** is expressed by folder presence:

- **One platform constant is the validity gate.** A `Domain` `StrEnum` (with a
  derived membership set) is the controlled set of domains. Every validity check —
  snippet classification, the `--domains` CLI filter, the SessionStart
  `command_domain` gate, cross-project ID classification — resolves against the
  constant, never a publish union.
- **Publication is convention, not declaration.** Distribution composes each
  registered root's existing `docs/global/<domain>/` folders, validating each
  folder name against the constant. Folder presence IS publication; multi-publisher
  contribution to the same domain merges as before, with snippet-id uniqueness the
  only cross-publisher guard.
- **The `business` config surface is removed entirely.** `business.domains`,
  `business.publishes`, and the `BusinessConfig` value object that held them are
  deleted from the schema — no empty shell is kept. `ProjectConfig` is
  `extra="allow"`, so an existing `teleclaude.yml` still carrying a `business:`
  key loads without error — the key is tolerated and ignored, requiring no
  fleet-wide config migration.

The universal-awareness and on-demand-depth model of ADR-0059 is unchanged: every
project still sees every published domain as a one-line index and loads depth on
demand. Only the _source of validity_ changes — from a dynamic publish-union back
to a fixed constant.

## Consequences

- Validity is decided in one place. Adding a domain is a one-line constant edit
  plus a `docs/global/<domain>/` folder, not a declaration that must propagate
  through registered configs before the domain is recognized.
- The bootstrap outage class is removed: a new domain's first publisher is valid
  the moment its folder exists, with no declaration ordering dependency.
- Removing the whole `business` surface is backward-safe by virtue of
  `ProjectConfig`'s `extra="allow"`; unmigrated configs keep loading. Every
  project drops its now-dead `business` block; nothing in the platform reads it.
- The constant is a `StrEnum` (the closed-vocabulary type the platform mandates,
  as for snippet scope and taxonomy), so illegal domain values are unrepresentable
  rather than policed by a scanner.

## Alternatives Considered

- **Keep the publish-union but seed it with a constant.** Rejected: retains the
  circularity and a second source of truth (declarations plus constant) for the
  same fact.
- **Derive validity from `docs/global/` folder presence alone (no constant).**
  Rejected: validity would then depend on what happens to exist on disk at scan
  time, with no controlled vocabulary to reject a typo'd or rogue folder name.
  Folder presence governs _publication_; the constant governs _validity_.

## See Also

- docs/project/adr/0059-domain-publication-and-universal-awareness.md

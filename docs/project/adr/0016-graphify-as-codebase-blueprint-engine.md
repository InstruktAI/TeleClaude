---
adr_status: 'accepted'
date: '2026-06-06'
description: 'Adopt the Graphify CLI (graphifyy, MIT) as-is as the codebase blueprint engine, lazy-generated under .teleclaude/blueprint, consumed via the CLI. No wrapper, no telec verb mapping, no MCP. The integration seam is the graph.json data contract plus the CLI method, not the vendor identity, so the engine is replaceable at low cost.'
number: '16'
visibility: 'public'
---

# ADR-0016: Adopt Graphify CLI as the Codebase Blueprint Engine — ADR

## Context

Agents in the SDLC need the blast radius of a change before they plan it —
which callers, importers, subclasses, and tests a change can touch. Today they
explore ad hoc with grep and file reads, so they miss scope, duplicate logic,
and under-estimate impact; review catches some of it, too late. The
`code-intelligence-foundation` todo set out to fix this by giving agents a
structural map of the codebase.

We evaluated build-vs-buy for the extraction engine and assessed Graphify
specifically (see `docs/third-party/graphify/overview.md` for the grounded
research). Graphify is an AST knowledge-graph builder (tree-sitter, MIT,
`graphifyy` on PyPI) covering our stack — Python, TypeScript, Rust, Go — with
local, API-free code extraction. We benchmarked it on this repo: a cold extract
of 185 files took ~5s, an incremental `--update` ~1s, and `query`/`affected`
returned in well under a second. We also confirmed two mechanics by reading the
source: `affected` is an unbounded-depth reverse-dependency traversal (a true
transitive blast radius from a seed), and the MCP server's `get_pr_impact` /
`triage_prs` tools measure community-spread risk, **not** reverse-dependency
impact.

## Decision

Adopt the Graphify CLI as-is as the codebase blueprint engine.

- The blueprint is `.teleclaude/blueprint/graph.json` plus a `manifest.json`
  freshness sidecar (`baseline_sha`, `generated_at`, `status`), gitignored. The
  integrator regenerates it on a successful remote-main pull with the pinned
  **no-LLM code refresh `graphify update <repo-root>`** (`extract` is the full
  AST+LLM path and is not used — code/AST only, no backend key).
- **Two thin platform surfaces, not a verb-for-verb wrapper** (this refines the
  earlier "agents use graphify directly" stance to satisfy the CLI-first default
  and the single-owner boundary):
  - **`telec context blueprint affected <changed-files>`** — the agent-facing
    blast-radius primitive (changed-files → symbol node-ids → `affected` → union,
    freshness-checked). It exists because `graphify affected` resolves only unique
    symbol seeds and Graphify has no file→dependents primitive. This is a value-add
    primitive, not a passthrough.
  - The integrator's `graphify update` generation step (above).
  - For discovery/reachability, agents still call `graphify query` / `graphify path`
    directly against the baseline. **No MCP server; no 1:1 verb mapping of Graphify.**
- The integration **seam is the `graph.json` data contract plus the CLI method**,
  not the vendor identity. We depend on a data shape and a discovery method, both
  of which another engine could satisfy.
- `affected` (per-symbol, unbounded depth) is the underlying blast-radius primitive;
  the MCP is not used — it is query-only and lacks symbol-level `affected`.

## Consequences

- **Near-zero build.** We reproduce nothing: tree-sitter extraction, call-graph,
  and the `affected` traversal come for free. The only code we own is the thin
  consumption discipline (a procedure) and the generation wiring.
- **Local and private.** Code extraction is AST-only — no LLM backend, no API
  key, no egress. The semantic/document pass (which would need a backend) is out
  of scope for v0.
- **Deliberate, contained coupling.** Agent-facing docs name `graphify` commands
  directly — accepted, not hidden. The blast radius of a future swap is contained
  because only one procedure and the generation step name the tool, and both sit
  above the stable `graph.json` shape. Replacing the engine means emitting the
  same `graph.json` from another producer; nothing else in the agent surface
  changes.
- **Mechanics agents must respect** (encoded in the procedure): seed `affected`
  on **symbols, not files** (files do not cascade); disambiguate common names by
  passing the node id; bias to over-inclusion because false negatives
  (build-time surprises) cost far more than false positives (a discarded read);
  name invisible-coupling categories (dynamic dispatch, registry/string wiring,
  config-driven behavior, cross-language, reflection) as explicit blind spots.
- **Dependency risk.** Graphify is young (v0.8.x), fast-moving (daily releases),
  and effectively solo-maintained. Mitigations: pin the version; rely on the
  `graph.json` seam so replacement is a contained change rather than a rewrite.

## Alternatives Considered

- **Verb-for-verb `telec` wrapper.** Rejected: a 1:1 rename is a maintenance
  burden and false decoupling — it still breaks when the underlying surface moves,
  while adding a mapping to keep in sync.
- **MCP-only consumption.** Rejected: the MCP server is query-only over a
  pre-built graph, lacks symbol-level `affected`, and its PR-impact tools report
  community-spread risk rather than reverse-dependency blast radius.
- **Build our own extractor now.** Deferred: the `graph.json` seam lets us defer
  this until/unless Graphify disappoints. Writing a tree-sitter emitter that
  produces the same shape is a contained future option, not an upfront cost.
- **`graphify-rs` (Rust port).** Rejected for now: an independent third-party
  rewrite (~37 stars, `NOASSERTION` license) that follows the Python upstream.
  Reconsider only if a native binary or its extra analyses (cycle detection,
  PageRank) become load-bearing and its licensing clears.

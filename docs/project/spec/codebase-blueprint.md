---
description: "The codebase Blueprint — a generated AST structural map agents consult at plan time for an intended change's blast radius. Engine (Graphify CLI), integrate-time generation, freshness manifest, the telec context blueprint affected helper, languages, and blind spots."
visibility: 'public'
---

# Codebase Blueprint — Spec

## What it is

The **Blueprint** is a generated, structural map of the project's source —
symbols (functions, classes, modules) and the dependency edges between them
(calls, imports, inheritance, uses), parsed per-language. Agents (at plan time
especially) consult it to obtain the **blast radius** of an intended change —
the dependents a change can affect — instead of grepping and re-reading files.

It is a capability of the `context` bounded context (file-based context
engineering that primes and equips agents); the Blueprint is structural code
context delivered to agents. The `context` domain spec
(`project/spec/domain/context`) indexes this capability once its own rewrite
lands; this spec is the self-standing contract in the meantime. The engine is
the Graphify CLI, adopted as-is behind the `graph.json` data-contract seam (see
`project/adr/0016-graphify-as-codebase-blueprint-engine`).

## Canonical fields

### Ubiquitous language

**Blueprint**
: The generated structural map (`graph.json`) plus its freshness manifest. A project-root cache, gitignored, shared across worktrees.

**Blast-radius (affected set)**
: For an intended change to a symbol or file, the dependents it can affect — callers, importers, subclasses, tests — derived by reverse-traversal of the Blueprint's dependency edges. The structural input to a plan's change surface.

**Blind spot**
: A coupling the Blueprint cannot see because it is not a source-level edge — dynamic dispatch, registry/string-keyed wiring, config-driven behavior, reflection, and every cross-language boundary (Python↔Rust↔TypeScript via FFI/IPC/process). Named explicitly so the agent reads those areas manually rather than trusting an incomplete blast radius.

### Artifact & freshness manifest

`.teleclaude/blueprint/graph.json` plus a sidecar `.teleclaude/blueprint/manifest.json`
carrying `baseline_sha` (the `origin/main` commit the graph was built from),
`generated_at`, and `status`. Both live at the project root, gitignored, shared
across worktrees (like `todos.db`). The manifest is the freshness signal: a
consumer compares `baseline_sha` to the current main baseline and treats a
mismatch / missing manifest / non-`ok` `status` as stale.

### Languages

Python, Rust, TypeScript — one graph spanning all three. Python and Rust are
high-fidelity: most symbols carry their dependents, and blast-radius is dense.
TypeScript extracts and queries, and traces type and interface imports well — a
shared `types.ts` surfaces its full fan-in. Its dependency graph is materially
sparser everywhere else: component and runtime wiring (`.tsx`, barrel
`index.ts`, default exports, dynamic imports) is largely unmodeled, so most
TypeScript files report an empty or thin blast-radius. For TypeScript an empty
or thin `affected` result is low-confidence — read it as "the Blueprint cannot
see the dependents," never as "there are none," and fall back to manual
exploration.

### Generation (automation, never agents)

`integration` is the single writer. On a successful remote-main pull it runs the
pinned no-LLM refresh `graphify update <repo-root>` and writes `graph.json` +
`manifest.json` (see the integration design's _Blueprint regeneration_).
`context` owns the contract (location, manifest schema, languages, the query
surface); `integration` owns the write because the Blueprint is a generated
cache, not authoritative state — a deliberate divergence from the single-owner
default. Pinned and installed via `make install`.

### Agent how-to (consumption)

The plan-time blast-radius discipline lives in the `plan-draft` procedure. The
agent-facing surface is **`telec context blueprint affected <changed-files>`** —
the one value-add primitive (changed-files → symbol node-ids → `affected` →
union, freshness-checked against the manifest), which exists because `graphify
affected` resolves only unique symbol seeds and Graphify has no file→dependents
primitive of its own. Blueprint generation is not a public verb. For discovery
and reachability, `graphify query "<terms>"` and `graphify path` read the same
baseline directly.

### Fallback

If the manifest reports stale/missing, the area is unsupported, or a Blind spot
applies, the agent states the gap and falls back to manual exploration —
blast-radius is never silently skipped.

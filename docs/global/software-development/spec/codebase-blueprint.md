---
description: "The codebase Blueprint — a generated AST structural map of the project's source that agents consult for an intended change's blast radius. Engine (Graphify CLI), integrate-time generation, freshness manifest, the telec context blueprint affected command surface, languages, and blind spots."
visibility: 'public'
---

# Codebase Blueprint — Spec

## What it is

The **Blueprint** is a generated, structural map of the project's source —
symbols (functions, classes, modules) and the dependency edges between them
(calls, imports, inheritance, uses), parsed per-language. Agents consult it to
obtain the **blast radius** of an intended change — the dependents a change
can affect — instead of grepping and re-reading files. When and how to consult
it is codified in `software-development/procedure/blast-radius-discovery`; this
spec is the canonical reference for what it is and where it lives.

It is a capability of the `context` bounded context (file-based context
engineering that primes and equips agents); the Blueprint is structural code
context delivered to agents. The `context` domain spec
(`project/spec/domain/context`) indexes this capability once its own rewrite
lands; this spec is the self-standing contract in the meantime. The engine is
the Graphify CLI, adopted as-is behind the `graph.json` data-contract seam.

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
across worktrees (like `.teleclaude/todos.db`). The manifest is the freshness
signal: a consumer compares `baseline_sha` to the current `origin/main`
baseline and treats a mismatch / missing manifest / non-`ok` `status` as stale.

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

<!-- planned-change:repair-context-blueprint-blast-radius -->

`integration` is the single writer. On a successful remote-main pull it runs the
pinned no-LLM refresh `graphify update <repo-root>` and writes `graph.json` +
`manifest.json` (see the integration design's _Blueprint regeneration_).
`context` owns the contract (location, manifest schema, languages, the command
surface); `integration` owns the write because the Blueprint is a generated
cache, not authoritative state — a deliberate divergence from the single-owner
default. Pinned and installed via `make install`.

<!-- change:repair-context-blueprint-blast-radius -->

`integration` is the single writer. On a successful remote-main pull it runs the
pinned no-LLM refresh `graphify update <repo-root> --force` (the `--force`
override lets a code-deleting refactor's smaller re-extraction overwrite the
cache instead of persisting a `status=error`) and writes `graph.json` +
`manifest.json` (see the integration design's _Blueprint regeneration_).
`context` owns the contract (location, manifest schema, languages, the command
surface); `integration` owns the write because the Blueprint is a generated
cache, not authoritative state — a deliberate divergence from the single-owner
default. Pinned and installed via `make install`.

<!-- /planned-change:repair-context-blueprint-blast-radius -->

### Command surface

The agent-facing surface is **`telec context blueprint affected <changed-files>`** —
the one value-add primitive (changed-files → symbol node-ids → `affected` →
union, freshness-checked against the manifest), which exists because `graphify
affected` resolves only unique symbol seeds and Graphify has no file→dependents
primitive of its own. Blueprint generation is not a public verb. For discovery
and reachability against the same baseline, use `graphify query "<terms>"`,
`graphify explain "<symbol>"`, and `graphify path "<A>" "<B>"`. `query` and a
few other subcommands are functional but omitted from `graphify --help`'s
listing — verify with the command itself, not the help text, if a subcommand
appears to be missing.

### Fallback

If the manifest reports stale/missing, the area is unsupported, or a Blind spot
applies, the agent states the gap and falls back to manual exploration —
blast-radius is never silently skipped.

## See Also

- ~/.teleclaude/docs/software-development/procedure/blast-radius-discovery.md — when and how to consult the Blueprint before editing.

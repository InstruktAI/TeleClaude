---
description: "The codebase Blueprint — a generated AST structural map of the project's source that agents consult for an intended change's blast radius. Engine (Graphify CLI), integrate-time generation, freshness manifest, the telec code blueprint affected command surface, languages, and blind spots."
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

Its object is the repository's own source, which is what the `code` capability
expresses, so its agent surface lives in the `telec code` namespace and is
meaningful only in a project that has source. No domain spec claims the
Blueprint; this spec is its self-standing contract. The engine is the Graphify
CLI, adopted as-is behind the `graph.json` data-contract seam.

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

Blueprint regeneration runs automatically — never by agents — from three
disjoint triggers:

- A **`post-merge` git hook** on the repo root runs the pinned no-LLM refresh
  `graphify update <repo-root> --force` whenever a merge changes `HEAD`. `git pull`
  is fetch+merge, so a manual pull of the repo root regenerates the Blueprint. The
  hook resolves the repo root from `GRAPHIFY_REPO_ROOT`. The integrator's own git
  operations set a suppression signal the hook honors, so the hook fires only for
  external pulls.
- The **integrator regenerates directly after a confirmed delivery** — from the
  repo root when its post-delivery pull synced to `origin/main`, and from the
  integration worktree, which holds the delivered commit, when that pull diverged.
- The **command surface dispatches a detached refresh when it observes a stale
  baseline from the canonical checkout** and answers the current call from the
  fallback. Regeneration runs in a separate process group so the command returns
  immediately, and a non-blocking lock makes it single-flight: an observation
  made while a refresh is already running dispatches nothing. An observation made
  from a todo worktree answers the fallback and dispatches nothing, so a slug
  checkout never drives the shared cache. This trigger covers every path by which
  `origin/main` advances without a merge or a delivery — most commonly a commit
  authored on main at the repo root and pushed, for which git offers no hook —
  so the baseline converges without an agent ever invoking generation.

The `--force` override lets a code-deleting refactor's smaller re-extraction
overwrite the cache instead of persisting a `status=error`. Every trigger writes
`graph.json` + `manifest.json` at the project root. This spec owns the contract
(location, manifest schema, languages, the command surface); the write is a
generated cache, not authoritative state — a deliberate divergence from the
single-owner default. Pinned and installed via `make install`.

### Command surface

The agent-facing surface is **`telec code blueprint affected <changed-files>`** —
the one value-add primitive (changed-files → symbol node-ids → `affected` →
union, freshness-checked against the manifest), which exists because `graphify
affected` resolves only unique symbol seeds and Graphify has no file→dependents
primitive of its own. It requires the `code` capability, like the rest of the
`telec code` namespace. Blueprint generation is not a public verb. For discovery
and reachability against the same baseline, use `graphify query "<terms>"`,
`graphify explain "<symbol>"`, and `graphify path "<A>" "<B>"`. `query` and a
few other subcommands are functional but omitted from `graphify --help`'s
listing — verify with the command itself, not the help text, if a subcommand
appears to be missing.

### Fallback

If the manifest reports stale/missing, the area is unsupported, or a Blind spot
applies, the agent states the gap and falls back to manual exploration —
blast-radius is never silently skipped.

### Use cases

#### UC-BP1: A stale baseline dispatches its own refresh

```gherkin
Given the Blueprint manifest records a baseline commit that is not the current origin/main
When an agent asks the command surface for the blast radius of a changed file from the canonical checkout
Then the command answers with the manual-exploration fallback naming the stale baseline
And it dispatches a detached regeneration for the current origin/main baseline
But an agent asking the same question from a todo worktree receives the fallback with no regeneration dispatched
```

## See Also

- ~/.teleclaude/docs/software-development/procedure/blast-radius-discovery.md — when and how to consult the Blueprint before editing.

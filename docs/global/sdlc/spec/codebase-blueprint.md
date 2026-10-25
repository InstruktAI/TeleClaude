---
description: "The codebase Blueprint — a generated AST structural map of the project's source that agents consult for an intended change's blast radius. Engine (Graphify CLI), integrate-time generation, freshness manifest, the blast-radius command surface, languages, and blind spots."
visibility: 'public'
---

# Codebase Blueprint — Spec

## What it is

The **Blueprint** is a generated, structural map of the project's source —
symbols (functions, classes, modules) and the dependency edges between them
(calls, imports, inheritance, uses), parsed per-language. Agents consult it to
obtain the **blast radius** of an intended change — the dependents a change
can affect — instead of grepping and re-reading files. When and how to consult
it is codified in `sdlc/procedure/blast-radius-discovery`; this
spec is the canonical reference for what it is and where it lives.

Its object is the repository's own source. Its agent surface lives in the
`telec repo` namespace, and this spec is its contract. The engine is the
Graphify CLI, adopted as-is behind the `graph.json` data-contract seam.

## Canonical fields

### Ubiquitous language

**Blueprint**
: The generated structural map (`graph.json`) plus its freshness manifest. A project-root cache, gitignored, shared across worktrees.

**Blast-radius (affected set)**
: For an intended change to a symbol or file, the dependents it can affect — callers, importers, subclasses, tests — derived by reverse-traversal of the Blueprint's dependency edges. The structural input to a plan's change surface.

**Blind spot**
: A coupling the Blueprint cannot see because it is not a source-level edge — dynamic dispatch, registry/string-keyed wiring, config-driven behavior, reflection, and every cross-language boundary (Python↔Rust↔TypeScript via FFI/IPC/process). Named explicitly so the agent reads those areas manually rather than trusting an incomplete blast radius.

### Artifact & freshness manifest

The graph and freshness manifest form one committed generation at the owning
project root, gitignored and shared across worktrees. The manifest identifies
the exact committed canonical-main revision extracted, its generation time,
and the generation outcome. Freshness compares that revision with canonical
main, independently of whether it has been pushed. A worktree reads the owning
checkout's baseline rather than its own branch.

Publication activates a complete graph and matching manifest together. A
consumer pins one generation while reading it; an unsuccessful or interrupted
extraction does not activate an incomplete generation. These invariants follow
the explicit state and concurrency ownership in
`sdlc/policy/code-quality-practices`.

### Installed source baseline

When a project's installation contract selects an immutable release checkout,
that checkout's Blueprint baseline is its selected installed commit. Generation,
freshness checks and recovery consume the same committed-source selection from
the owning maintenance boundary. Canonical-main baseline rules apply to other
checkouts. Source ownership and consistent reads follow
`sdlc/policy/domain-ownership` and `sdlc/policy/code-quality-practices`.

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

Blueprint generation is deterministic canonical-main maintenance in projects
that enable the code capability. Every canonical-main commit or merge
activation owes that maintenance, including documentation-only advances and
empty commits. Git returns after recording the obligation and starting the
maintenance executor; extraction completes through that executor. A commit or
merge in a linked worktree changes no shared Blueprint baseline.

The maintenance action extracts an isolated snapshot of a committed
canonical-main revision and publishes to the owning checkout's shared cache.
Uncommitted files and branch-only work are outside that snapshot. The action
converges to the latest committed main tip observed when it runs; an already
current generation completes without re-extraction. Each obligation retains
its activation identity, while its outcome identifies the revision actually
extracted. A later obligation remains eligible after an earlier action ends,
and replay converges forward rather than restoring an older cache.

All extraction and publication share one writer serialization boundary.
Generation failure is a failed maintenance outcome with a recovery reference.
On-demand maintenance performs the same action as recovery. Query surfaces
consume the resulting generation and observe maintenance completion; generation
has no public command verb. The engine remains pinned and installed through
the project's toolchain. A smaller valid extraction can replace a larger graph.

One maintenance owner and reuse of the existing executor follow
`sdlc/principle/design-fundamentals`; publication and failure outcomes follow
`sdlc/policy/code-quality-practices`.

### Command surface

The agent-facing surface is **`telec repo blueprint affected <changed-files>`** —
the one value-add primitive (changed-files → symbol node-ids → `affected` →
union, freshness-checked against the manifest), which exists because `graphify
affected` resolves only unique symbol seeds and Graphify has no file→dependents
primitive of its own. It requires the `code` capability. Blueprint generation is
not a public verb. For discovery
and reachability against the same baseline, use `graphify query "<terms>"`,
`graphify explain "<symbol>"`, and `graphify path "<A>" "<B>"`. `query` and a
few other subcommands are functional but omitted from `graphify --help`'s
listing — verify with the command itself, not the help text, if a subcommand
appears to be missing.

<!-- planned:code-uc-blueprint-traceability -->

### Delivery traceability

Blueprint supplements structural traversal with lifecycle-derived use-case
associations. An exact `spec_id + UC-id` resolves approved plan bindings, the
todo that owns each binding, and the actual source paths in its delivery commit.
An in-flight plan contributes its declared referenced paths until delivery;
after delivery, the commit diff is the implementation fact.

The projection works in both directions. A changed source path can expose use
cases linked through in-flight plans or delivered commits. A use case can expose
the plans, delivery commits, and source paths that carried it, which then seed
the existing structural affected view. Plan, commit, and graph provenance remain
distinct; none is presented as a function-level semantic assertion.

For every linked delivery, Blueprint compares the current fenced Gherkin block
with the same `spec_id + UC-id` at the delivery commit. A content difference is
reported as predicate drift. Git owns the historical snapshot, so no authored
revision number, stored fingerprint, source annotation, or migration step is
required.

The projection is computed from current todo artifacts, delivery records, Git,
and the existing Blueprint at invocation time. It introduces no durable index,
global use-case namespace, source-code metadata contract, or synchronization
gate. Missing associations are reported as missing evidence rather than proof
that no implementation exists.
<!-- /planned:code-uc-blueprint-traceability -->

### Fallback

A successful blast-radius query uses a complete generation matching committed
canonical main at the query's freshness observation. A fresh query answers
immediately. A query encountering outstanding Blueprint maintenance observes
its completion within the query's bounded wait, then rechecks freshness and
reads one consistent generation. Canonical and worktree callers receive the
same shared-baseline guarantee.

A failed, absent, interrupted, or overdue refresh, an unresolved canonical-main
revision, or an unreadable graph yields an explicit unavailable result with
the applicable maintenance recovery reference. The agent states the gap and
uses manual exploration. An older graph is retained cache state, not a
successful current answer. Unsupported languages and blind spots retain the
manual exploration contract above. Failure visibility follows
`sdlc/principle/design-fundamentals`.

### Use cases

#### UC-BP1: A query observes current maintenance before answering

```gherkin
Given the shared Blueprint is behind committed canonical main
And automatic Blueprint maintenance is outstanding
When an agent asks for the blast radius of a changed file
Then the query observes maintenance completion within its wait bound
And a successful answer uses a complete graph matching committed canonical main at its freshness observation
And the query performs no extraction itself
```

#### UC-BP2: A slug-worktree merge preserves the shared baseline

```gherkin
Given an agent is working in a todo worktree with branch-only changes
And the shared Blueprint reflects committed canonical main
When the agent merges upstream main into that worktree
Then the shared Blueprint continues to reflect committed canonical main
And no branch-only structure becomes visible to Blueprint consumers
```

## See Also

- ~/.teleclaude/docs/sdlc/procedure/blast-radius-discovery.md — when and how to consult the Blueprint before editing.

---
description: 'AI-driven project doc-snippet onboarding invoked by /project-onboard-docs (telec projects onboard-docs / onboard). Guides the session through codebase discovery, convention inference, and idempotent snippet generation that re-runs safely as the codebase evolves.'
visibility: 'public'
delivered_by: ['project-onboard-tooling-and-docs']
---

# Project Onboard Docs — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/normalized-agent-artifacts.md
- @~/.teleclaude/docs/general/principle/intent-first-documentation.md
- @~/.teleclaude/docs/software-development/principle/documentation-first-development.md
- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/general/policy/snippet-value-contract.md
- @~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md
- @~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md
- @~/.teleclaude/docs/general/spec/agent-artifacts.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @~/.teleclaude/docs/software-development/spec/init-scaffolding.md

## Goal

Analyze a codebase systematically and produce durable, project-specific doc snippets that
make the repository legible to AI from the first session. Every generated snippet must
reflect concrete findings from the analyzed repository, not generic templates.

## Preconditions

- The project has source files (not an empty repository).
- `telec projects init` plumbing (hooks, sync, project registration) has already completed; the operator invoked `telec projects onboard-docs` or `telec projects onboard`.
- The required reads above provide the output contract (`init-scaffolding`),
  the snippet-authoring discipline (`doc-snippet-authoring`, which transitively
  pulls in the value contract, schema, and referencing rules), and the
  agent-artifact governance (for the AGENTS.master.md decision in Step 15).
- The session runs inside the project root with full filesystem read access.

## Steps

### 1. Orientation

Determine the project's primary characteristics before deep analysis:

- Read `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`,
  `pom.xml`, `build.gradle`, or equivalent to identify language and package manager.
- Read the project root directory listing to identify top-level structure.
- Check for existing `teleclaude.yml`, `docs/project/`, and `AGENTS.md` to
  understand current TeleClaude integration state.
- If the project already has `generated_by: telec-init` snippets, this is a
re-analysis. Note existing snippet IDs for merge decisions.
<!-- planned:onboard-docs-incremental-enrichment -->
- Read `.telec-init-meta.yaml`. When it records a `last_analyzed_commit`, this
is an incremental re-run: compute `git diff <last_analyzed_commit>..HEAD
  --name-only` and scope the analysis and snippet refresh to the changed
areas, leaving snippets whose source is unchanged untouched. When the file
is absent or carries no commit, analyze the full tree (first run).
<!-- /planned:onboard-docs-incremental-enrichment -->

### 2. Language and Framework Detection

Identify all languages and frameworks in use:

- **Python:** Check `pyproject.toml`, `setup.py`, `requirements.txt`. Identify
  web frameworks (Django, Flask, FastAPI), CLI frameworks (Click, Typer), test
  frameworks (pytest, unittest), async patterns (asyncio, trio).
- **TypeScript/JavaScript:** Check `package.json` dependencies and devDependencies.
  Identify frameworks (React, Next.js, Express, Hono, Svelte), bundlers (Vite,
  webpack, esbuild), test runners (Vitest, Jest, Mocha).
- **Go:** Check `go.mod`. Identify web frameworks (Gin, Echo, Chi), CLI frameworks
  (Cobra, urfave/cli).
- **Rust:** Check `Cargo.toml`. Identify frameworks (Actix, Axum, Rocket), async
  runtimes (Tokio, async-std).
- **Other languages:** Identify from file extensions and build files.

### 3. Entry Points and Route/Handler Mapping

Locate the primary entry points:

- Main executables, CLI entry points, server bootstrap files.
- Route definitions, API handler registrations, middleware chains.
- Event handlers, message consumers, webhook receivers.
- Scheduled jobs or cron-like registrations.

### 4. Architecture Pattern Recognition

Identify the dominant architecture:

- Layer structure (MVC, hexagonal, clean architecture, monolith, microservice).
- Module organization (feature-based, layer-based, domain-driven).
- State management patterns (global state, dependency injection, actor model).
- Communication patterns (REST, GraphQL, gRPC, WebSocket, message queues).
- Database access patterns (ORM, raw SQL, repository pattern).

#### Brownfield domain and documentation classification

Before authoring any snippet, classify what the evidence is asking the doc
layer to represent. This classification is part of analysis, not a post-write
cleanup pass.

- **Bounded context discovery:** identify candidate contexts from service or
  module boundaries, state ownership, domain vocabulary, entry points, emitted
  or consumed events, and persistence boundaries. A package, directory, or
  class is not automatically a bounded context; it earns that treatment only
  when it owns a coherent domain model.
- **Domain specs:** author or refresh `project/spec/domain/<context>` only
  when a bounded context is evidenced. The spec names ubiquitous language,
  aggregates, domain events, use cases, and context-map position in domain
  terms. Do not replace this with a flat `project/concept/domain-model`
  summary.
- **Feature specs:** author or refresh
  `project/spec/feature/<context>/<concept>` only for Category A
  user-visible product capabilities. The concept is a durable product/domain
  noun, never the onboarding run slug and never a tooling cleanup label.
- **Contract or tooling refinements:** route service contracts, CLI surfaces,
  generated-doc behavior, conventions, and scaffolding rules to the relevant
  domain spec, tool spec, policy, procedure, or design doc. Do not create a
  feature spec for work whose audience is agents or operators.
- **Current versus target truth:** onboarding analysis is code-grounded
  inventory. Generated snippets describe current behavior; they carry no
  `delivered_by` (absence = current). Design-delivery snippets that describe
  intended future state carry `delivered_by: [<owning-slug>]`; do not invent
  those during brownfield analysis.
- **Skip:** if the candidate only restates source files, repeats global
  policy, or fills a taxonomy slot without changing future-agent behavior, do
  not author it.

### 5. Test Pattern and Coverage Model

Characterize the testing approach:

- Test framework and runner configuration.
- Test directory structure and naming conventions.
- Test categories present (unit, integration, e2e, contract, snapshot).
- Fixture and mock patterns.
- Coverage configuration if present.

### 6. Dependency Inventory and Role Classification

Catalog dependencies with their roles:

- **Core:** Framework, runtime, and language dependencies.
- **Data:** Database drivers, ORMs, cache clients.
- **Infrastructure:** Logging, monitoring, configuration.
- **Development:** Test frameworks, linters, formatters, build tools.
- **Integration:** API clients, SDK wrappers, protocol libraries.

### 7. Build and Deploy Model

Document the build and deployment pipeline:

- Build commands and scripts (`Makefile`, `package.json` scripts, CI config).
- Containerization (Dockerfile, docker-compose).
- CI/CD configuration (GitHub Actions, GitLab CI, etc.).
- Environment configuration and secrets management.

### 8. Configuration Structure

Map the configuration landscape:

- Config file formats and locations (YAML, JSON, TOML, env files).
- Environment variable patterns.
- Feature flags or conditional configuration.
- Multi-environment setup (dev, staging, production).

### 9. Git History Patterns

Sample recent git history for conventions:

- Commit message style (conventional commits, free-form, ticket references).
- Branching model (trunk-based, gitflow, feature branches).
- Review patterns (PR-based, direct push, approval requirements).
- Release tagging conventions.

### 10. Existing Documentation Inventory

Catalog what documentation already exists:

- README files and their coverage.
- API documentation (OpenAPI specs, generated docs).
- Architecture decision records (ADRs).
- Inline documentation density and style.
- Existing `docs/` directory content.

### 11. Sampling Strategy for Large Codebases

When the project exceeds comfortable analysis within a single context window:

- **File count > 500:** Focus on top-level structure, entry points, and
  configuration. Sample 2-3 representative modules deeply rather than
  scanning everything shallowly.
- **Monorepo:** Analyze the root package manifest and shared infrastructure
  first, then the largest or most active package.
- **Directory prioritization:** `src/`, `lib/`, `app/`, `cmd/` before
  `vendor/`, `node_modules/`, `dist/`, `build/`.
- **Fallback:** When context is tight, produce fewer but higher-quality
  snippets rather than attempting comprehensive but shallow coverage.

### 12. Convention Inference Rules

Infer project conventions from evidence, not assumptions:

- **Naming:** Sample function, variable, and file names across modules. Report
  the dominant style (camelCase, snake_case, PascalCase, kebab-case).
- **Error handling:** Look for patterns — do functions return errors, throw
  exceptions, use Result types? Is there a custom error hierarchy?
- **Logging:** Identify the logging library and structured vs. unstructured
  patterns.
- **Import organization:** Note grouping conventions (stdlib first, third-party
  second, local third) and absolute vs. relative import preference.

### 13. Decision Boundaries

- **Infer:** When evidence is unambiguous (e.g., all files use snake_case,
  there is exactly one framework, commit messages consistently follow a format).
- **Preserve ambiguity:** When evidence is mixed or insufficient. Write
  "observed X in some files, Y in others" rather than picking one.
- **Leave placeholder for human follow-up:** When the analysis cannot determine
  intent (e.g., is a complex module intentionally structured that way or
  is it technical debt?). Mark with `<!-- human-review: reason -->`.

### 14. Snippet Output

Generated snippets must:

- Conform to the scaffolding schema (`software-development/spec/init-scaffolding`).
- Use `project/` scope IDs from the scaffolding schema. Flat IDs such as
  `project/design/architecture` remain valid; nested spec IDs are reserved for
  earned domain specs and Category A feature specs.
- Include `generated_by: telec-init` and `generated_at: <ISO8601>` in frontmatter.
- Declare `visibility` deliberately. Default to `internal`. Promote a single
  snippet to `public` only when both hold: (a) the content reveals nothing
  sensitive (no credentials, no private infra topology, no internal personnel
  routing, no non-public business intel, no personal data), and (b) the content
  is genuinely useful to an outsider asking the project's help desk. When in
  doubt, keep it `internal` — the analyzer never bulk-publishes by reflex.
- Reference concrete findings: real package names, actual file paths, observed
  patterns — never generic placeholder text.
- Cover the categories implied by the analyzed codebase. Not every category
  applies to every project.

Apply the value test from `general/policy/snippet-value-contract` to every
candidate snippet. The table below names common project-snippet shapes worth
considering. Each row is conditional on the value test: if a candidate fails
— for example, if the project's "structure" or "conventions" are generic and
add no signal beyond what stdlib, framework, or global policy already imply —
do not produce that snippet. Coverage is not a virtue; signal is. When the
project implements a global policy, prefer a reverse pointer (`See also: <global policy ID>`)
over restating the contract.

| Snippet shape                              | Taxonomy | Worth producing when…                                                                                                                                                                           |
| ------------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `project/spec/domain/<context>`            | spec     | A bounded context is evidenced by coherent domain vocabulary, state ownership, events, entry points, and invariants.                                                                            |
| `project/spec/feature/<context>/<concept>` | spec     | A user-visible product capability is present and needs durable business value plus Gherkin scenarios. Never use this for tooling, contract cleanup, or generic code inventory.                  |
| `project/design/architecture`              | design   | Repo structure encodes durable intent the code cannot express — non-obvious layering, a deliberate constraint, or topology agents must navigate.                                                |
| `project/policy/conventions`               | policy   | Conventions diverge from the language's global policy in ways agents must respect (custom error hierarchy, project-specific naming). The global policy answers the rest.                        |
| `project/spec/dependencies`                | spec     | Dependency choices encode constraints invisible in the manifest (why a version is pinned, why a library was chosen over alternatives). Otherwise the manifest is the source of truth.           |
| `project/spec/entry-points`                | spec     | Entry points have non-obvious wiring (conditional registration, side-effect imports). Otherwise a 30-second source read answers it.                                                             |
| `project/design/test-strategy`             | design   | The project tests in non-standard ways agents must follow (custom fixtures, coverage philosophy, specific frameworks). Generic pytest/jest patterns do not earn a snippet.                      |
| `project/spec/build-deploy`                | spec     | The pipeline encodes constraints invisible in the CI YAML (why a step exists, what failure it defends). Otherwise the YAML is the source of truth.                                              |
| `project/spec/configuration`               | spec     | Configuration semantics are project-specific. **If the project implements a global policy, write a reverse pointer (`See also: <global policy ID>`) and stop — do not duplicate the contract.** |

### 15. Agent Bootstrap Content (AGENTS.master.md decision)

The init analysis encounters one of four normal repository states. The
decision determines whether to create or promote `AGENTS.master.md`. Apply
the matching case; do not improvise.

**Case 1 — `AGENTS.master.md` exists.** Respect it. Do not modify. The
existing source is authoritative.

**Case 2 — Hand-authored `AGENTS.md` exists, no master.** Promote it. By
convention `CLAUDE.md` is a shim (`@./AGENTS.md`) or absent in this case.
Procedure:

- Move the content of `AGENTS.md` into a new `AGENTS.master.md`.
- Run `telec sync`.
- Verify the regenerated `AGENTS.md` (inflated from the master, possibly with
  baseline additions) and the `CLAUDE.md` shim are produced. The original
  content survives in `AGENTS.master.md`.

**Case 3 — Substantive standalone `CLAUDE.md`, no `AGENTS.md`.** Respect by
default. Do not auto-create a master — a substantive standalone `CLAUDE.md`
is a deliberate Claude-Code-only signal. Promotion to a master is possible
but only as an explicit human-driven step, never as part of automated init
analysis.

**Case 4 (greenfield) — no `AGENTS.master.md`, no `AGENTS.md`, no
substantive `CLAUDE.md`.** Generate a minimal project-specific
`AGENTS.master.md` capturing tech stack, key directories, and primary
conventions. Subsequent `telec sync` inflates `AGENTS.md` and writes the
`CLAUDE.md` shim.

**Anomaly — both substantive `AGENTS.md` and substantive `CLAUDE.md`.** This
contradicts the shim convention. Halt automatic promotion and flag the
conflict for human inspection. Do not auto-promote: a subsequent `telec sync`
would overwrite `CLAUDE.md` with the shim and silently destroy its content.
The human must decide which file is authoritative before the analysis
proceeds.

## Outputs

- A set of schema-valid doc snippets under `docs/project/`.
- A concise summary of what was created/updated.
- A `telec sync --skip-deploy` run confirming snippet validity.
<!-- planned:onboard-docs-incremental-enrichment -->
- An updated `.telec-init-meta.yaml` recording `last_analyzed_commit` set to the
HEAD commit analyzed, so the next run has a diff base.
<!-- /planned:onboard-docs-incremental-enrichment -->

## Recovery

- If analysis fails mid-run, any snippets already written are valid and
  can be kept. The session should report what was completed and what remains.
- Re-running analysis is safe — the merge rules prevent duplication and
  preserve human edits.

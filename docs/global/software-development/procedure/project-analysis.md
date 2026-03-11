---
id: 'software-development/procedure/project-analysis'
type: 'procedure'
scope: 'domain'
description: 'AI-driven project analysis procedure for telec init enrichment. Guides the analysis session through codebase discovery, convention inference, and snippet generation.'
---

# Project Analysis — Procedure

## Goal

Analyze a codebase systematically and produce durable, project-specific doc snippets that
make the repository legible to AI from the first session. Every generated snippet must
reflect concrete findings from the analyzed repository, not generic templates.

## Preconditions

- The project has source files (not an empty repository).
- `telec init` plumbing (hooks, sync, watchers) has already completed.
- The scaffolding schema (`software-development/spec/init-scaffolding`) is loaded
  as a required read so the analysis session knows the output contract.
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
- Use `project/` scope IDs (e.g., `project/design/architecture`).
- Include `generated_by: telec-init` and `generated_at: <ISO8601>` in frontmatter.
- Reference concrete findings: real package names, actual file paths, observed
  patterns — never generic placeholder text.
- Cover the categories implied by the analyzed codebase. Not every category
  applies to every project.

The analysis determines which snippets to produce based on what exists:

| Snippet ID | Taxonomy | When to generate |
|---|---|---|
| `project/design/architecture` | design | Always (every project has structure) |
| `project/policy/conventions` | policy | When naming/style conventions are observable |
| `project/spec/dependencies` | spec | When the project has external dependencies |
| `project/spec/entry-points` | spec | When entry points or routes are identified |
| `project/design/test-strategy` | design | When tests exist |
| `project/spec/build-deploy` | spec | When build/deploy config exists |
| `project/spec/configuration` | spec | When config files are present |

### 15. Agent Bootstrap Content

When no project-local `AGENTS.master.md` or equivalent artifact source exists:

- Generate a minimal project-specific agent bootstrap snippet that describes
  the project, its tech stack, key directories, and primary conventions.
- The content should be concise enough to fit in the agent's pre-loaded context.
- Do not overwrite existing agent artifact sources — respect the artifact
  governance rules.

## Outputs

- A set of schema-valid doc snippets under `docs/project/`.
- A concise summary of what was created/updated.
- A `telec sync --validate-only` run confirming snippet validity.

## Recovery

- If analysis fails mid-run, any snippets already written are valid and
  can be kept. The session should report what was completed and what remains.
- Re-running analysis is safe — the merge rules prevent duplication and
  preserve human edits.

# Requirements: telec-init-enrichment

## Goal

Transform `telec init` from a plumbing command (hooks, sync, watchers) into an
intelligence bootstrapping command that makes a raw codebase legible to AI. After
enrichment, every future AI session starts with understanding instead of cold discovery.

## Problem Statement

A fresh project initialized with `telec init` gets infrastructure (git hooks, doc
watchers, `teleclaude.yml`) but no intelligence layer. The AI has no architecture docs,
no convention awareness, no dependency maps. Each session rediscovers the same codebase
from scratch. The maturity gap prevents the project from benefiting from TeleClaude's
SDLC capabilities.

## Scope

### In scope

1. **Project analysis engine** — deep codebase read triggered during `telec init`:
   - Language and framework detection
   - Entry point and route/handler mapping
   - Architecture pattern recognition (monolith, microservices, monorepo, etc.)
   - Test pattern identification (frameworks, naming conventions, coverage model)
   - Package dependency inventory and role classification
   - Build and deploy model (scripts, CI, containerization)
   - Configuration structure (env vars, config files, feature flags)
   - Git history patterns (commit style, branching model, release cadence)
   - Existing documentation inventory (README, inline docs, comments, wikis)

2. **Documentation scaffolding** — turn analysis into durable doc snippets:
   - Architecture snippet(s) derived from actual code structure
   - Convention/policy stubs inferred from codebase patterns
   - Dependency map from package files
   - Entry point documentation from route/handler analysis
   - Project-specific baseline content for `AGENTS.md`
   - Generated snippets placed under `docs/project/` with correct frontmatter

3. **Authorized author guidance** — a procedure doc snippet consumed by the AI during
   analysis that defines:
   - What to look for per language/framework
   - How to structure findings as doc snippets
   - How to infer conventions from git history and code patterns
   - How to produce useful `AGENTS.md` content (not generic templates)
   - When to ask the human vs. when to infer

4. **Init flow integration** — extend `init_project()` to offer enrichment after plumbing:
   - Detect first-time init vs. re-init
   - On first init: prompt user to run enrichment or skip
   - On re-init: offer to refresh analysis
   - Enrichment runs as an AI session (via `telec sessions start`)
   - Session produces doc snippets, commits them, and ends

5. **Idempotency** — enrichment is safe to re-run:
   - Re-analysis updates existing snippets rather than duplicating
   - User-modified snippets are preserved (not overwritten)
   - Analysis metadata tracks what was auto-generated vs. human-authored

### Out of scope

- Event emission during init (`project.initialized` events) — deferred until
  `event-envelope-schema` is delivered.
- Mesh registration during init — deferred until `mesh-architecture` is delivered.
- Progressive automation level detection — emergent property, not a built feature.
- Cross-project analysis (analyzing relationships between projects).
- Third-party doc research during init (user can run `telec docs` commands separately).

## Success Criteria

- [ ] `telec init` on a fresh project (with code) produces at least: one architecture
      snippet, one convention snippet, and one dependency map snippet under `docs/project/`.
- [ ] Generated snippets pass `telec sync --validate-only` (correct frontmatter, IDs,
      taxonomy structure).
- [ ] Generated snippets appear in `telec docs index` output after init.
- [ ] `telec docs get <generated-snippet-id>` returns meaningful, project-specific content.
- [ ] Authorized author guidance doc exists and is consumed by the analysis session.
- [ ] Re-running enrichment on an already-analyzed project updates (not duplicates) snippets.
- [ ] User-edited snippets are not overwritten by re-analysis.
- [ ] Enrichment session ends cleanly after producing artifacts.
- [ ] Existing `telec init` plumbing (hooks, watchers, sync) continues to work unchanged.

## Constraints

- The analysis AI session must operate within a single context window — the codebase
  analysis cannot require multi-session orchestration.
- Generated snippets must follow the existing snippet authoring schema (frontmatter
  with `id`, `description`, `type`, `scope`, `visibility`).
- The enrichment step must be optional — `telec init` without enrichment must still work
  as it does today (plumbing only).
- No new daemon dependencies — enrichment uses existing session infrastructure.

## Risks

- Large codebases may exceed a single session's analysis capacity. Mitigation: the
  authorized author guidance should define sampling strategies for large projects.
- AI-generated documentation may contain inaccuracies. Mitigation: all generated
  snippets are marked as auto-generated and presented for human review.
- Snippet ID conflicts with manually authored snippets. Mitigation: use a reserved
  prefix or namespace for auto-generated snippets (e.g., `project/init/architecture`).

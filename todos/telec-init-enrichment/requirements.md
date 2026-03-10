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
   - Git history patterns (commit style, branching model, [inferred] release cadence)
   - Existing documentation inventory (README, inline docs, comments, [inferred] wikis)

2. **Documentation scaffolding** — turn analysis into durable doc snippets:
   - Architecture snippet(s) derived from actual code structure
   - Convention/policy stubs inferred from codebase patterns
   - Dependency map from package files
   - Entry point documentation from route/handler analysis
   - [inferred] Project-specific agent bootstrap content for `AGENTS.md`, with any
     Claude companion behavior staying consistent with agent artifact governance
   - [inferred] Generated snippets placed under `docs/project/{taxonomy}/` per the snippet
     authoring schema (e.g., `docs/project/design/` for architecture, `docs/project/policy/`
     for conventions) — each snippet in its correct taxonomy type directory

3. **Authorized author guidance** — a procedure doc snippet consumed by the AI during
   analysis that defines:
   - What to look for per language/framework
   - How to structure findings as doc snippets
   - How to infer conventions from git history and code patterns
   - How to produce useful `AGENTS.md` content (not generic templates)
   - When to ask the human vs. when to infer

4. **[inferred] Init flow integration** — `telec init` offers enrichment after plumbing:
   - Detect first-time init vs. re-init
   - On first init: prompt user to run enrichment or skip
   - On re-init: offer to refresh analysis
   - Enrichment runs through the existing session infrastructure
   - Session produces doc snippets, commits them, and ends

5. **[inferred] Idempotency** — enrichment is safe to re-run:
   - Re-analysis updates existing snippets rather than duplicating
   - User-modified snippets are preserved (not overwritten)
   - Analysis metadata tracks what was auto-generated vs. human-authored

6. **[inferred] Local TeleClaude integration** — the initialized project remains
   connected to the existing local TeleClaude surfaces:
   - Project registration uses the existing local project catalog behavior so the repo
     becomes discoverable after sync
   - Release-channel setup uses the existing project deployment channel configuration
     surface instead of introducing a parallel subscription mechanism
   - Any user-facing `telec init` help text or prompts reflect the enrichment step and
     any release-channel choice it exposes

### Out of scope

- Event emission during init (`project.initialized` events) — deferred until
  `event-envelope-schema` is delivered.
- Mesh registration during init — deferred until `mesh-architecture` is delivered.
- Progressive automation level detection — emergent property, not a built feature.
- [inferred] Cross-project analysis (analyzing relationships between projects).
- [inferred] Third-party doc research during init (user can run `telec docs` commands separately).

## Success Criteria

- [ ] `telec init` on a fresh project (with code) produces at least: one architecture
      design snippet, one convention policy snippet, and one dependency spec snippet —
      each under its correct taxonomy directory (`docs/project/design/`, `docs/project/policy/`,
      `docs/project/spec/`).
- [ ] [inferred] Generated snippets pass `telec sync --validate-only` (correct frontmatter, IDs,
      taxonomy structure).
- [ ] [inferred] Generated snippets appear in `telec docs index` output after init.
- [ ] [inferred] `telec docs get <generated-snippet-id>` returns non-empty, project-specific
      content that includes repo identifiers discovered during analysis (for example package names,
      entry points, or config files), not generic placeholder text.
- [ ] [inferred] Authorized author guidance doc exists, and the enrichment session input
      references that guidance explicitly enough for a test double or transcript assertion to prove
      it was used.
- [ ] [inferred] Re-running enrichment on an already-analyzed project updates (not duplicates) snippets.
- [ ] [inferred] User-edited snippets are not overwritten by re-analysis.
- [ ] [inferred] After init on a project with `teleclaude.yml`, the local TeleClaude project
      catalog contains a live entry for the repo that points at `docs/project/index.yaml`.
- [ ] [inferred] If init configures a non-default release channel, the project records it using
      the existing `deployment.channel` and `deployment.pinned_minor` config fields rather than a
      new config surface.
- [ ] [inferred] User-facing `telec init` help text or prompt copy reflects the enrichment option.
- [ ] [inferred] The enrichment session reports a successful completion outcome and does not remain
      active after artifact generation.
- [ ] [inferred] Existing `telec init` plumbing (hooks, watchers, sync) continues to work unchanged.

## Constraints

- The analysis AI session must operate within a single context window — the codebase
  analysis cannot require multi-session orchestration.
- Generated snippets must follow the existing snippet authoring schema (frontmatter
  with `id`, `description`, `type`, `scope`, and optional `role`).
- The enrichment step must be optional — `telec init` without enrichment must still work
  as it does today (plumbing only).
- No new daemon dependencies — enrichment uses existing session infrastructure.
- [inferred] Local project registration and release-channel handling must reuse the existing
  project catalog and deployment-channel surfaces rather than creating new global mechanisms.

## Risks

- Large codebases may exceed a single session's analysis capacity. Mitigation: the
  authorized author guidance should define sampling strategies for large projects.
- AI-generated documentation may contain inaccuracies. Mitigation: all generated
  snippets are marked as auto-generated and presented for human review.
- Snippet ID conflicts with manually authored snippets. Mitigation: use a consistent
  naming convention for auto-generated snippets within the standard taxonomy
  (e.g., `project/design/architecture`, `project/policy/conventions`) and mark them
  with `generated_by` frontmatter metadata to distinguish from human-authored snippets.

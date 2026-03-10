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
   - Architecture pattern recognition
   - Test pattern identification
   - Package dependency inventory and role classification
   - Build and deploy model
   - Configuration structure
   - Git history patterns
   - Existing documentation inventory

2. **Documentation scaffolding** — turn analysis findings into durable doc snippets
   that conform to the existing snippet authoring schema. The analysis determines
   which snippets to produce and which taxonomy types to use based on what the
   codebase contains. [inferred] Project-specific agent bootstrap content for
   `AGENTS.md` is included, consistent with agent artifact governance.

3. **Authorized author guidance** — a procedure doc snippet consumed by the AI
   during analysis that encodes the discovery dimensions, per-language checklists,
   convention inference rules, snippet structuring guidance, and decision boundaries
   for when to infer vs. leave placeholders for human follow-up.

4. **[inferred] Init flow integration** — `telec init` offers enrichment after plumbing:
   - Detect first-time init vs. re-init
   - On first init: prompt user to run enrichment or skip
   - On re-init: offer to refresh analysis
   - Enrichment runs through the existing session infrastructure
   - Session produces doc snippets, commits them, and ends

5. **[inferred] Idempotency** — enrichment is safe to re-run:
   - Re-analysis updates existing snippets rather than duplicating
   - User-modified snippets are preserved (not overwritten)
   - Auto-generated snippets are distinguishable from human-authored ones

### Out of scope

- Event emission during init (`project.initialized` events) — deferred until
  `event-envelope-schema` is delivered.
- Mesh registration during init — deferred until `mesh-architecture` is delivered.
- Progressive automation level detection — emergent property, not a built feature.
- [inferred] Cross-project analysis (analyzing relationships between projects).
- [inferred] Third-party doc research during init (user can run `telec docs` commands separately).

## Success Criteria

- [ ] `telec init` on a fresh project (with code) produces schema-valid, project-specific
      doc snippets that are discoverable via `telec docs index` and `telec docs get`.
- [ ] Generated snippet content reflects the actual codebase (package names, entry points,
      patterns found) — not generic placeholder text.
- [ ] The analysis session uses the authorized author guidance during its run.
- [ ] Re-running enrichment updates existing auto-generated snippets without duplicating
      them and without overwriting human-edited snippets.
- [ ] The enrichment session completes and does not remain active after artifact generation.
- [ ] Existing `telec init` plumbing (hooks, watchers, sync) continues to work unchanged
      when enrichment is declined.
- [ ] [inferred] User-facing `telec init` help text reflects the enrichment option.

## Constraints

- The analysis AI session must operate within a single context window — the codebase
  analysis cannot require multi-session orchestration.
- Generated snippets must conform to the existing snippet authoring schema.
- The enrichment step must be optional — `telec init` without enrichment must still work
  as it does today (plumbing only).
- No new daemon dependencies — enrichment uses existing session infrastructure.
- [inferred] No new config surfaces — any configuration produced during init reuses
  existing config fields.

## Risks

- Large codebases may exceed a single session's analysis capacity. Mitigation: the
  authorized author guidance should define sampling strategies for large projects.
- AI-generated documentation may contain inaccuracies. Mitigation: the demo step
  validates output quality, snippets are marked as auto-generated so the human
  knows the provenance, and re-analysis preserves any human edits.
- Snippet ID conflicts with manually authored snippets. Mitigation: auto-generated
  snippets are distinguishable from human-authored ones.

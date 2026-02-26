# Requirements: skills-procedure-taxonomy-alignment

## Goal

Move procedural workflow logic out of exploratory skill wrappers into documentation procedures, then align the corresponding wrappers to a breath-aware taxonomy model while preserving current behavior and artifact validity.

## Problem Statement

Exploratory skill workflows are currently encoded directly in `agents/skills/*/SKILL.md`, which mixes wrapper concerns with long-form operational procedure content. This increases drift risk and weakens documentation reuse.

## Scope

### In scope

- Define exploratory breath-aware taxonomy boundaries for this todo pass.
- Extract procedural logic from selected exploratory skills into docs procedure snippets.
- Update selected exploratory `SKILL.md` files to wrapper-style prompts that reference procedure docs through `## Required reads`.
- Keep skill artifacts valid for distribution/validation tooling.
- Provide explicit verification commands and observable outcomes.

### Out of scope

- Non-exploratory skills.
- `agents/commands` or `agents/` persona artifacts.
- Runtime behavior changes in `teleclaude/` daemon or adapters.
- Host service lifecycle/process-management changes.
- Third-party integration additions.

## Functional Requirements

### R1. Exploratory taxonomy contract

Document the exploratory lane definition and explicitly list which skills are in scope for this todo.

### R2. Procedure extraction

For each in-scope exploratory skill, create a corresponding procedure doc that contains the workflow logic currently embedded in the skill wrapper.

### R3. Wrapper alignment

Each in-scope `SKILL.md` remains schema-valid but is reduced to wrapper-level guidance and references the extracted procedure via `## Required reads`.

### R4. Behavior preservation

The wrapper + procedure combination must preserve current operational intent (no loss of mandatory constraints or critical anti-pattern guards from current skills).

### R5. Toolchain compatibility

`telec sync` and artifact validation/distribution flows must continue to succeed after the migration.

### R6. Traceable verification

The todo must include concrete commands and observable checks proving:

- taxonomy definition exists,
- procedures exist,
- wrappers point to them,
- validation passes.

## Success Criteria

- [ ] Exploratory taxonomy definition exists in docs and names the in-scope skills.
- [ ] Every in-scope exploratory skill has one mapped procedure doc.
- [ ] Every in-scope exploratory `SKILL.md` has `## Required reads` pointing to its mapped procedure doc.
- [ ] In-scope wrappers satisfy skill artifact schema requirements (frontmatter + required sections).
- [ ] `telec sync` completes successfully.
- [ ] Targeted validation/tests for artifact structure and distribution pass.
- [ ] No runtime code paths in `teleclaude/` are modified by this todo.

## Verification Strategy

Suggested verification commands:

1. `telec sync`
2. `python -m pytest tests/unit/test_resource_validation.py -k skill`
3. `python -m pytest tests/unit/test_distribute_local_codex.py`
4. `rg -n "^## Required reads|^# " agents/skills/*/SKILL.md`
5. `rg --files docs/global/software-development/procedure`

## Dependencies & Preconditions

- `telec sync` is available and configured in this environment.
- Current skill wrappers and docs tree remain writable.
- No prerequisite roadmap todo is required for docs-only extraction.

## Constraints

- Preserve existing skill names and folder names.
- Keep changes limited to skills/docs for this slug.
- Do not alter host-level service configuration.

## Risks

- Misclassification risk: skill included/excluded from exploratory lane without explicit contract.
- Drift risk: extracted procedure omits constraints previously embedded in wrappers.
- Discoverability risk: procedures created but not consistently referenced.

## Resolved Decisions

1. **Exploratory skill roster for this pass:** The 5 unmigrated skills with exploratory character:
   - `brainstorming` — divergent design exploration
   - `systematic-debugging` — root cause diagnosis
   - `next-silent-failure-hunter` — error path diagnosis
   - `tech-stack-docs` — documentation research
   - `youtube` — information gathering/research

   The 7 already-migrated skills (next-code-reviewer, next-code-simplifier, next-comment-analyzer, next-test-analyzer, next-type-design-analyzer, research, git-repo-scraper) already have `## Required reads` referencing policy/spec docs. They still contain inline procedures but are a follow-up pass — not this todo.

2. **Procedure path convention:** Use existing `docs/global/{domain}/procedure/` tree. Name for the activity, not the skill:
   - `brainstorming` → `docs/global/general/procedure/socratic-design-refinement.md`
   - `systematic-debugging` → `docs/global/software-development/procedure/root-cause-debugging.md`
   - `next-silent-failure-hunter` → `docs/global/software-development/procedure/silent-failure-audit.md`
   - `tech-stack-docs` → `docs/global/software-development/procedure/research/tech-stack-documentation.md`
   - `youtube` → `docs/global/general/procedure/youtube-research.md`

3. **Baseline manifests:** Follow-up. This todo creates docs and validates via `telec sync`; manifest inclusion is a separate lightweight step.

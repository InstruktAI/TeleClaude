# Implementation Plan: skills-procedure-taxonomy-alignment

## Approach

Use a docs-first migration:

1. Define exploratory taxonomy boundaries.
2. Extract workflow logic into procedure snippets.
3. Convert skill files to thin wrappers that point to those procedures.
4. Validate with existing sync/validation toolchain.

This follows existing artifact conventions (`## Required reads`, snippet schema, skill schema) already used in the repository.

## Requirement Traceability

| Task                                               | Requirement(s) |
| -------------------------------------------------- | -------------- |
| Task 1: Exploratory roster decision + taxonomy doc | R1             |
| Task 2: Author per-skill procedure docs            | R2, R4         |
| Task 3: Convert skill wrappers to aligned wrappers | R3, R4         |
| Task 4: Validation and sync                        | R5, R6         |

## Tasks

### Task 1: Define exploratory scope and taxonomy source of truth

- [x] Task complete

**Files:**

- `docs/global/general/concept/skill-taxonomy.md`

**Actions:**

- Define breath-aware taxonomy lanes (exploratory, disciplinary, creative) with exploratory as the focus of this pass.
- List the 5 in-scope exploratory skills with brief rationale.
- Record exclusion rationale for the 4 non-exploratory unmigrated skills (receiving-code-review, test-driven-development, verification-before-completion, frontend-design).
- Note the 7 already-migrated skills as future-pass candidates.

**Verification:**

- Taxonomy doc exists and explicitly lists in-scope skills.

### Task 2: Extract procedures for each in-scope exploratory skill

- [x] Task complete

**Files:**

- `docs/global/general/procedure/socratic-design-refinement.md` (from brainstorming)
- `docs/global/software-development/procedure/root-cause-debugging.md` (from systematic-debugging)
- `docs/global/software-development/procedure/silent-failure-audit.md` (from next-silent-failure-hunter)
- `docs/global/software-development/procedure/research/tech-stack-documentation.md` (from tech-stack-docs)
- `docs/global/general/procedure/youtube-research.md` (from youtube)

**Actions:**

- Create one procedure snippet per in-scope skill.
- Migrate operational logic (steps, constraints, anti-patterns) from wrappers into these docs.
- Keep each procedure compliant with snippet schema.
- Name files for the activity, not the skill (per naming policy).

**Verification:**

- One-to-one mapping exists between in-scope skills and procedure docs.
- Procedure snippets pass schema checks through `telec sync`.

### Task 3: Align in-scope skill wrappers

**Files:**

- `agents/skills/brainstorming/SKILL.md`
- `agents/skills/systematic-debugging/SKILL.md`
- `agents/skills/next-silent-failure-hunter/SKILL.md`
- `agents/skills/tech-stack-docs/SKILL.md`
- `agents/skills/youtube/SKILL.md`

**Actions:**

- Keep required frontmatter (`name`, `description`) unchanged.
- Keep required skill sections (`Purpose`, `Scope`, `Inputs`, `Outputs`, `Procedure`).
- Add or update `## Required reads` references to mapped procedure docs.
- Remove duplicated long-form procedure logic from wrappers while preserving intent.

**Verification:**

- Skill validation passes (`tests/unit/test_resource_validation.py -k skill`).
- Wrapper docs show correct `@` references and section order.

### Task 4: Validate and record readiness evidence

**Actions:**

- Run `telec sync`.
- Run targeted unit tests for skill/distribution validation.
- Capture observed outputs in demo artifacts and DOR notes.

**Verification:**

- `telec sync` exits successfully.
- Targeted tests pass.

## Build Sequence

1. Task 1
2. Task 2
3. Task 3
4. Task 4

## Assumptions

1. This todo is documentation/skill-artifact only (no runtime code edits).
2. Existing distribution tooling supports wrappers that rely on `## Required reads` inlined refs (confirmed: 7 skills already use this pattern).
3. Exploratory skill roster is finalized at 5 skills (see Resolved Decision Points).

## Resolved Decision Points

1. **Exploratory roster** (5 skills): brainstorming, systematic-debugging, next-silent-failure-hunter, tech-stack-docs, youtube.
2. **Procedure path convention**: `docs/global/{domain}/procedure/{activity-name}.md`, using existing tree structure. See requirements.md §Resolved Decisions for full mapping.

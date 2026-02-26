# Skills Procedure Taxonomy Alignment

## Context

Current skill procedures in `agents/skills/*/SKILL.md` contain substantial operational guidance directly in the skill bodies.

We want tighter control and better philosophical alignment by moving procedural content into documentation snippets (procedures), then making skills thinner wrappers that point to those procedures through `## Required reads`.

This work is explicitly scoped to **repo-owned skills only**:

- `agents/skills/`

## Objective

Create an extraction/migration plan and implementation path to:

1. Extract procedural guidance from `agents/skills/*/SKILL.md` into the docs procedure taxonomy.
2. Align the extracted procedures with breath framing (inhale/hold/exhale) where it improves clarity.
3. Update skills to reference procedure snippets instead of embedding long procedures.
4. Keep rollout pragmatic: no strict new validation gates in this phase.

## Scope

### In scope

- Audit all 16 skills in `agents/skills/`.
- Map each skill procedure to one of:
  - existing procedure snippet (reuse),
  - new procedure snippet (create),
  - mixed (reuse + new supplement).
- Propose target snippet locations and rationale for each extraction.
- Execute migration in small batches.

### Out of scope

- Any skill outside `agents/skills/`.
- Runtime inventories under home directories.
- New hard enforcement checks that could block iteration.

## Initial extraction map (draft, exploratory)

### Batch A: core engineering workflow (high leverage first)

1. `systematic-debugging`
   - Target: `docs/global/software-development/procedure/debugging/systematic-root-cause.md`
   - Why: clear repeatable 4-phase method, broadly reusable.
2. `test-driven-development`
   - Target: `docs/global/software-development/procedure/testing/tdd-red-green-refactor.md`
   - Why: canonical behavior-shaping procedure with explicit checkpoints.
3. `verification-before-completion`
   - Target: `docs/global/software-development/procedure/quality/verification-before-claims.md`
   - Why: completion-claim safety gate should be centrally governed.
4. `receiving-code-review`
   - Target: `docs/global/software-development/procedure/review/handling-review-feedback.md`
   - Why: review response protocol belongs in shared procedure docs.

### Batch B: documentation/research operation skills

5. `tech-stack-docs`
   - Reuse: `docs/global/software-development/procedure/research/third-party-research.md`
   - Add: `docs/global/general/procedure/research/stack-docs-scope-routing.md`
   - Why: current skill adds global-vs-project storage routing not captured elsewhere.
6. `git-repo-scraper`
   - Add: `docs/global/general/procedure/research/git-repo-ingestion.md`
   - Why: helper invocation + artifact/update rules are currently skill-only.
7. `research`
   - Reuse: `docs/global/software-development/procedure/research/third-party-research.md` + `docs/global/general/spec/history-log.md`
   - Add only if gaps remain after consolidation.
8. `youtube`
   - Add: `docs/global/general/procedure/research/youtube-discovery-transcripts.md`
   - Why: operational helper constraints/circuit breaker are procedure-grade behavior.

### Batch C: design/planning skills

9. `brainstorming`
   - Add: `docs/global/software-development/procedure/design/brainstorming-before-implementation.md`
   - Why: design-first + one-question cadence + explicit approval gate should be centrally reusable.
10. `frontend-design`
    - Add: `docs/global/software-development/procedure/design/frontend-distinctive-direction.md`
    - Why: concrete design workflow and anti-patterns currently embedded only in skill text.

### Batch D: review lane specialization skills

11. `next-code-reviewer`
12. `next-test-analyzer`
13. `next-silent-failure-hunter`
14. `next-type-design-analyzer`
15. `next-comment-analyzer`
16. `next-code-simplifier`

- Reuse baseline: `docs/global/software-development/procedure/lifecycle/review.md`
- Add: lane-specific procedures under `docs/global/software-development/procedure/review-lanes/`
- Why: lane heuristics (scoring/rubrics/output format) are still skill-embedded.

## Breath alignment intent

Apply breath as framing during extraction, without forcing ceremony:

- **Inhale**: discovery/expansion steps (gather context, enumerate options, locate risks).
- **Hold**: tension/selection steps (trade-offs, hypothesis testing, critique, contradiction handling).
- **Exhale**: convergent outputs (verdicts, fixes, artifacts, handoff-ready structure).

If a procedure is purely mechanical, keep it direct and only include breath where it improves reasoning quality.

## Non-goals for this todo

- Do not add strict validation gates yet (for example, blocking sync if a skill has no procedure ref).
- Do not attempt one-shot migration of all skills in one commit.

## Expected deliverables

1. A confirmed extraction matrix (`skill -> target procedure doc(s) -> rationale`).
2. New/updated procedure snippets for migrated batches.
3. Corresponding skill updates in `agents/skills/*/SKILL.md` to use `## Required reads` and slimmer local instructions.
4. A short follow-up note on whether soft validation hints are useful later (non-blocking).

## Open questions to resolve during prepare

1. Should all extracted skill procedures live under `software-development`, or should cross-domain research skills live under `general`?
2. For review lane skills, is one lane-procedure-per-skill the right granularity, or should some lanes merge?
3. For breath language, what minimum standard keeps alignment useful without bloating skill context?

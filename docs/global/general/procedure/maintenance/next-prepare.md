---
id: 'general/procedure/maintenance/next-prepare'
type: 'procedure'
scope: 'global'
description: 'Execution procedure for next-prepare maintenance, including state-based handling for todo preparation artifacts.'
---

# Next Prepare Maintenance — Procedure

## Required reads

@~/.teleclaude/docs/software-development/policy/definition-of-ready.md
@docs/project/spec/jobs/next-prepare.md

## Goal

Run an idempotent maintenance pass that brings active todos to a high-quality
Definition-of-Ready state by improving preparation artifacts and recording
auditable results.

The same procedure is used for:

- single-slug execution (`slug` provided),
- batch execution (no `slug`, iterate active slugs needing work).

## Preconditions

1. Job was launched as `next-prepare` agent job.
2. `todos/roadmap.md`, `todos/icebox.md`, and `todos/delivered.md` are readable.
3. Slug is considered active only if it is not in icebox or delivered lists.
4. `state.json` exists or can be created for the target slug.

## Steps

1. Discover scope:
   - if `slug` provided: process only that slug,
   - else discover active slugs from roadmap and process those needing preparation work.
2. Discover active slugs (batch mode):
   - enumerate folders under `todos/`,
   - exclude system entries and non-slug files,
   - exclude slugs in `icebox.md` and `delivered.md`.
3. For each active slug, evaluate freshness skip:
   - if `dor-report.md` exists,
   - and is newer than `requirements.md` and `implementation-plan.md`,
   - and `state.json.dor.schema_version` matches current schema,
   - and `state.json.dor.status == "pass"`,
   - then skip this slug.
4. Identify artifact state for non-skipped slugs:
   - State A: only `input.md` present (brain dump)
   - State B: `requirements.md` present, `implementation-plan.md` missing
   - State C: `implementation-plan.md` present, `requirements.md` missing
   - State D: both present but stale/weak
   - State E: both missing
5. Apply ordered handling:
   - State A: derive `requirements.md` from `input.md`, then derive `implementation-plan.md`.
   - State B: derive `implementation-plan.md` from `requirements.md` (+ optional `input.md`).
   - State C: reconstruct `requirements.md` from plan + context, then reconcile plan.
   - State D: refine requirements first, then reconcile plan against updated requirements.
   - State E: create minimal placeholder `requirements.md` and `implementation-plan.md`, mark low score and blockers.
6. Run DOR quality assessment:
   - evaluate clarity, scope atomicity, verifiability, dependency correctness, and uncertainty control,
   - assign score `1..10`,
   - set status:
     - `pass` for `>= 8`,
     - `needs_work` for `< 8` with safe improvements applied,
     - `needs_human_review` for `< 7` when further safe improvement is not possible.
7. Enforce autonomy boundary:
   - improve structure and precision,
   - do not invent behavior or architecture unsupported by repo/docs context,
   - if blocked by uncertainty, stop editing and record blockers.
8. Write outputs for each assessed slug:
   - `dor-report.md` with verdict, changes, remaining gaps, and explicit human decisions needed,
   - update `state.json.dor` with assessment metadata.
9. For slug-targeted execution, if roadmap state is `[ ]` and both required files
   exist, transition roadmap to `[.]`.
10. Continue to next slug until batch completes.

## Outputs

1. `todos/{slug}/dor-report.md` for each processed active slug.
2. `todos/{slug}/state.json` updated with `dor` object:
   - `last_assessed_at`
   - `score`
   - `status`
   - `schema_version`
   - `blockers`
   - `actions_taken`
3. Improved `requirements.md` and/or `implementation-plan.md` where safe.

## Recovery

1. If a slug cannot be safely improved above threshold:
   - set `status = needs_human_review`,
   - include explicit blockers and decisions required.
2. If files are malformed or unreadable:
   - preserve originals,
   - write blocker details into `dor-report.md`,
   - continue with remaining slugs.
3. If batch fails midway:
   - keep completed slug outputs as audit trail,
   - rerun job; freshness rules make rerun safe and incremental.

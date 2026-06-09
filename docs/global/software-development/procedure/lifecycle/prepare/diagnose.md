---
description: 'Bug diagnosis phase. Reproduce, trace the root cause to code, and prescribe the fix and verification approach as a diagnosis artifact before any code change.'
domain: 'software-development'
needs_domain_baseline: 'True'
id: 'software-development/procedure/lifecycle/prepare/diagnose'
scope: 'domain'
type: 'procedure'
visibility: 'public'
activation_trigger: 'A bug todo is at the DIAGNOSE prepare phase and needs its root cause verified before planning the fix.'
---
# Bug Diagnose — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/debugging.md

## Goal

For a `bug`, produce a **verified diagnosis** before any fix is planned or written:
the root cause traced to specific code, plus a prescribed fix approach and a credible
verification approach. The output is the `diagnosis` artifact, which the plan phase
consumes and the plan reviewer validates. This phase **prescribes**; it does not open a
worktree, write production code, or commit — the builder writes the reproduction test
and the fix during `/next-build`.

This is the bug lane's front-of-funnel sensemaking step, analogous to PRD-drafting for a
feature: a bug's symptom under-determines the fix, so the diagnosis is the work that
makes the plan groundable.

## Preconditions

- `kind == bug` and the todo is at the `DIAGNOSE` lifecycle phase.
- `telec todo artifacts read {slug} input` exists with the reported symptom and discovery
  context.
- No `diagnosis` artifact exists yet (its presence is what advances the phase).

## Steps

1. **Read the symptom.** `telec todo artifacts read {slug} input`. Treat it as a real,
   reproducible defect until investigation proves otherwise (refuse bug-denial).
2. **Follow the systematic debugging procedure** — reproduce first, then bisect and
   isolate. Read the actual code paths; do not pattern-match a likely cause.
3. **Trace the root cause to specific code.** Name the file, function, and line range
   where the defect originates, with the evidence that ties the symptom to that code. An
   ungrounded or "likely" root cause is not a diagnosis.
4. **Prescribe the fix approach.** Describe the minimal change that addresses the root
   cause (not the symptom). Name the files/functions the fix will touch. Do not write or
   commit the fix.
5. **Prescribe the verification approach.** State exactly how the fix will be proven:
   - Where an executable reproduction is possible, specify the reproduction test (the
     behavior it asserts and the test surface it belongs to) so the builder writes it
     RED→GREEN.
   - Where the bug is in uncovered, timing-dependent, or e2e territory and no unit
     reproduction is credible, document the observable reproduction **and prescribe the
     functional/e2e coverage that must be built** to capture it — as concrete work the
     plan will carry. Missing coverage is a plan task, never a reason to skip
     verification.
6. **Write the `diagnosis` artifact** with these sections: `## Symptom` (referencing
   the `input` artifact), `## Root Cause` (code-grounded), `## Fix Approach`,
   `## Verification Approach`. Use stable headers so the plan can reference these
   diagnosis sections (root-cause, fix-approach, verification-approach) as upstream.
   `telec todo artifacts write {slug} diagnosis <content>`.
7. **Advance.** Call `telec todo prepare {slug}`. The state machine derives
   `PLAN_DRAFTING` next; the planner consumes the `diagnosis` and the plan reviewer
   validates it.

## Outputs

- A `diagnosis` artifact (root cause traced to code + fix approach + verification
  approach), referenced by the implementation-plan and validated at plan-review.
- No code changes and no worktree commits — prescription only.

## Pre-completion checklist

- The root cause names specific code (file/function/line) with supporting evidence.
- The verification approach is concrete: a named reproduction test, or a documented
  observable reproduction plus a prescribed coverage-building task.
- The `diagnosis` artifact uses the stable section headers above.

## Discipline

The failure this phase exists to prevent is diagnose-and-fix in one ungated breath,
which produces "delivered yet ineffective" fixes against unverified root causes. Two
slides to refuse: (1) starting to write or commit the fix here — this phase prescribes,
the builder executes; (2) asserting a plausible root cause without grounding it in the
actual code, or skipping verification because the bug is "hard to reproduce" — an
unreproducible bug earns a prescribed coverage-building task, not a hand-wave. The
diagnosis is judged by the cross-model plan reviewer; write it to be refuted, not to
look right.

## Recovery

- If the bug cannot be reproduced at all, document the investigation in the `diagnosis`
  artifact, prescribe the coverage needed to reproduce it, and proceed — the plan
  reviewer judges whether the verification approach is adequate. Do not fabricate a root
  cause to move forward.
- If investigation shows the reported behavior is correct (not a defect), record that in
  the `diagnosis` and surface it; the bug may need reclassification or closure rather
  than a fix.

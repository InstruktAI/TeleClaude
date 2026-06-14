---
activation_trigger: 'A bug todo is at the DIAGNOSE prepare phase and needs its root cause verified before planning the fix.'
description: 'Bug diagnosis phase. Reproduce and trace the root cause — the causal mechanism — to specific code, written as a diagnosis artifact before any fix is planned. Diagnosis grounds the cause and prescribes no fix.'
needs_domain_baseline: 'True'
visibility: 'public'
---

# Bug Diagnose — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/debugging.md

## Goal

For a `bug`, produce a **verified root cause** before any fix is planned or written:
the causal mechanism — _why_ the code produces the wrong behavior — traced backward to
the specific code where the bad value or state originates, with the evidence that ties
the symptom to it. The output is the `diagnosis` artifact, which the plan phase consumes
as grounded input and the plan reviewer validates.

Diagnosis grounds the cause and stops there. It opens no worktree, writes no production
code, commits nothing, and **prescribes no fix or verification approach** — the planner
decides the fix that removes the cause, and the builder writes it during `/next-build`.
A diagnosis that reaches for a fix has shifted its objective from _understand_ to
_alleviate_, and an objective of alleviation never reliably reaches cause.

This is the bug lane's front-of-funnel sensemaking step, analogous to PRD-drafting for a
feature: a bug's symptom under-determines the fix, so a grounded root cause is the work
that makes the plan groundable.

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
3. **Trace the cause, not the location.** A root cause is the causal mechanism: _why_ the
   code produces the wrong behavior. Trace backward from where the symptom surfaces to
   where the bad value or state **originates** — the first violated invariant, the first
   wrong value, the line that produces it. Naming where the error is _thrown_ or
   _observed_ is a restatement of the symptom located in code, not a diagnosis. The bar
   the artifact must clear: a reader can follow the mechanism and the evidence chain, not
   just a file and a line.
4. **If the cause will not ground, escalate — do not write.** A plausible or "likely"
   cause is not a root cause. If systematic investigation does not yield a grounded
   causal mechanism, do **not** write a diagnosis and do **not** advance. Escalate per
   Recovery.
5. **Write the `diagnosis` artifact** with these sections: `## Symptom` (referencing the
   `input` artifact) and `## Root Cause` (the causal mechanism traced to specific code,
   with the reproduction and evidence chain that grounds it). Use these stable headers so
   the plan and the plan reviewer reference the root-cause section as upstream.
   `telec todo artifacts write {slug} diagnosis <content>`.
6. **Advance.** Call `telec todo prepare {slug}`. The state machine derives
   `PLAN_DRAFTING` next; the planner consumes the root cause and derives the fix, and the
   plan reviewer validates that the root cause is a genuine causal mechanism.

## Outputs

- A `diagnosis` artifact carrying the verified root cause (causal mechanism traced to
  code + the evidence that grounds it), referenced by the implementation-plan and
  validated at plan-review.
- No fix or verification prescription, no code changes, no worktree commits — the cause
  is grounded; the planner owns the fix.

## Pre-completion checklist

- The root cause names the causal mechanism — where the bad value or state originates —
  not where the symptom surfaces, with the evidence chain that ties symptom to cause.
- The reproduction (or, where reproduction is not yet stable, the investigation that
  grounds the mechanism) is recorded as evidence.
- The `diagnosis` artifact carries only `## Symptom` and `## Root Cause`; it prescribes no
  fix and no verification.

## Discipline

The failure this phase exists to prevent is the diagnosis that restates the symptom and
calls it done — naming where the error surfaces instead of why it originates — and the
diagnosis that reaches past its job to prescribe a fix. Both let an unverified or
symptom-shaped premise flow into planning, producing "delivered yet ineffective" fixes
and fallback-shaped workarounds. Three slides to refuse: (1) accepting a located symptom
as a root cause; (2) prescribing a fix or verification approach here — diagnosis grounds
the cause, the planner decides the fix; (3) writing a "likely" cause to keep moving when
the mechanism will not ground — escalate instead. The diagnosis is judged by the
cross-model plan reviewer; write it to be refuted, not to look right.

## Recovery

A root cause that will not ground is the trigger to escalate, never to proceed. No path
advances an ungrounded or symptom-shaped diagnosis.

1. **Dispatch one independent diagnoser.** Start a single cross-model peer session on a
   different model (`telec sessions start --agent <other> --project <path> --message
"<brief>"`) with a **blind** brief: the `input` symptom and the codebase only — never
   your failed hypothesis. It investigates from scratch and **returns its assessment as
   session output; it writes no artifact.** Independence is the point — a peer anchored to
   your reasoning debugs your debugging, not the bug.
2. **Reconcile both trails.** Read the peer's assessment against your own, treating your
   prior hypothesis as the **prime suspect**, not the baseline. Take one more
   investigation pass with the combined awareness.
3. **Ground and proceed, or escalate and stop.** If the cause now grounds, write the
   `diagnosis` and advance. If it still will not ground, **escalate to the human and
   stop** — surface the union of both investigation trails (the evidence and the ruled-out
   space) so the human starts at the frontier. Do not fabricate a cause and do not advance
   an ungrounded diagnosis.

- If investigation shows the reported behavior is correct (not a defect), record that in
  the `diagnosis` and surface it; the bug may need reclassification or closure rather than
  a fix.

---
activation_trigger: 'A bug todo is at the DIAGNOSE prepare phase and needs its root cause verified before planning the fix.'
description: 'Bug diagnosis phase. Record the investigation, then trace the root cause — the causal mechanism — to specific code as a thin diagnosis grounded in that investigation, before any fix is planned. Diagnosis grounds the cause and prescribes no fix.'
needs_domain_baseline: true
visibility: 'public'
---

# Bug Diagnose — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/debugging.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md

## Goal

For a `bug`, produce a **verified root cause** before any fix is planned or written, in
two artifacts:

- **`investigation`** — the evidence substrate: the reproduction, the avenues walked,
  and the observations gathered, each recorded as a re-verifiable fact. Written whether
  or not the cause grounds; it is the pre-work a conclusion is built on and points to.
- **`diagnosis`** — the thin conclusion: the causal mechanism (_why_ the code produces
  the wrong behavior) traced to the specific code where the bad value or state
  originates, grounded in and referencing the `investigation`. Written only once the
  cause grounds.

The plan phase consumes the `diagnosis` and the plan reviewer validates that its root
cause is a genuine causal mechanism traceable to the investigation's evidence. The split
mirrors the `architecture` shape: a thin conclusion over a substantive substrate.

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
- No sibling bug for the same defect is already in flight — the duplicate triage (Step 1)
  enforces this before any artifact is written.

## Steps

<!-- planned:todo-creation-record -->

0. **Read the creation record first.** `telec todo show {slug}` exposes
   `entry_point`, `lineage`, `human_involved`, and `context` — which door filed
   this bug, whose hands acted, and whether a human observed the symptom. A
   human-door filing (`tui`/`cli`/`web`) means the reported symptom is a
   first-hand human observation; an agent-initiated filing
   (`human_involved=false`) means the organic trigger lives in that agent's
   session evidence, and the investigation traces it there rather than
   manufacturing a synthetic reproduction as a silent stand-in. When a
   reproduction must be constructed, the investigation labels it synthetic and
   either traces the organic path or records the organic trigger as untraced —
   an explicit open gap, never an implied equivalence.

<!-- /planned:todo-creation-record -->

1. **Triage for duplicate, suppression, or no-fix — before any investigation or artifact
   write.** Simultaneous log scans and human reports produce near-coincident reports of
   the same defect, each scaffolding its own bug todo. The report-time moment cannot catch
   this — each reporter checks before the other's todo exists — but by the time this phase
   runs the sibling already exists, so the triage lives here, ahead of the investigation
   and every artifact write. Read this todo's reported symptom for the comparison
   (`telec todo artifacts read {slug} input`), list the in-flight bugs
   (`telec bugs list`, `telec todo list`), read the active suppression ledger
   (`telec bugs suppressions`), and read the `input` of the candidates that look related.
   A **duplicate** is another bug todo whose reported defect shares the same root symptom
   — the same error signature, the same failing surface — not merely the same file or
   area; that judgment is yours to make from the symptoms, not a string match. Reading
   inputs and suppressions is the triage's own work; the hard gate is on investigation and
   artifact writes, never on the read the triage depends on.
   - **If a sibling for the same defect is already in flight, retire this todo as the
     duplicate.** Resolve the race deterministically so two simultaneous diagnose sessions
     never both retire themselves: the **survivor** is whichever twin is already further
     along (has an `investigation`/`diagnosis` or an active diagnose session); when both
     sit at the same fresh state, the survivor is the **earliest-created** todo,
     tie-broken by lexically-first slug. If this todo is not the survivor, remove it —
     `telec todo remove {slug}`, naming the surviving slug in the reason — and **end the
     session**. Write **no** `investigation` and **no** `diagnosis`: a todo about to be
     retired earns no artifacts, and the survivor owns the diagnosis.
   - **Hand forward material info — only when sure it helps.** Before removing, compare
     this twin's `input` against the survivor's todo. If this twin carries discovery
     context the survivor does not surface — a distinct reproduction, a second occurrence
     site, an environment detail — and you are **confident it is genuinely additive**,
     send a single informational message to the survivor's active session
     (`telec sessions send <session_id> "<info>"`) before retiring. Substance only: no
     acknowledgement, no echo, no narration. If you are not sure it adds, stay silent and
     just retire — silence is the default, a low-value message is noise that interrupts an
     agent mid-diagnosis.
   - **If the reported signal matches an active suppression, retire this todo as
     already-triaged.** A log-hunter signal already in the project's suppression
     ledger (`telec bugs suppressions`) was deliberately accepted as expected or
     won't-fix; treat it like a duplicate — remove the todo
     (`telec todo remove {slug}`, naming the suppression in the reason) and end
     the session, writing no `investigation` and no `diagnosis`.
   - **If the reported signal is itself a suppression or no-fix candidate, decide that
     before diagnosing.** Log-hunter bug reports sometimes describe correct operational
     behavior rather than a defect: external service throttles, stale duplicate cleanup,
     intentionally tolerated platform limits, or a report whose symptom was already fixed
     by a committed change. Do a short confirmation from the `input`, the active
     suppressions, and a targeted log check if needed; do not perform full root-cause
     investigation merely to prove an accepted no-fix classification. If the signal is a
     stable recurring condition that should not re-file, register the invariant pattern
     with `telec bugs suppress "<pattern>" --reason "<why>" --match regex
--disposition <expected|wontfix> --source-bug {slug}`, then remove the todo and end
     the session, writing no `investigation` and no `diagnosis`. If the signal was already
     fixed, one-off, or unlikely to recur, remove the todo and end the session **without**
     adding a suppression. If confidence is not high, keep the todo and proceed to Step 2;
     the cost of a false suppression is hiding a real bug.
   - **If this todo is the survivor, or no sibling exists, proceed to Step 2.**
2. **Read the symptom as a defect to investigate.** With the `input` already in hand from
   triage, treat it as a real, reproducible defect until investigation proves otherwise
   (refuse bug-denial).
   **Triage a fix-shaped input.** When the `input` names a missing capability or a
   solution rather than an observed wrong behavior ("X has no way to do Y", "add Z"),
   re-derive the symptom from evidence — the observable wrong behavior that prompted the
   report — and investigate that. The embedded solution is an unratified suggestion; it
   carries no authority into the diagnosis or the plan
   (`software-development/policy/process-change-authority`). A diagnosis that "verifies
   the absence of the proposed fix" has inherited the input's premise instead of tracing
   a cause.
3. **Investigate.** Follow the systematic debugging procedure — reproduce first, then
   bisect and isolate. Read the actual code paths; do not pattern-match a likely cause.
   **Trace the cause, not the location:** trace backward from where the symptom surfaces
   to where the bad value or state **originates** — the first violated invariant, the
   first wrong value, the line that produces it. Naming where the error is _thrown_ or
   _observed_ is a restatement of the symptom located in code, not a cause.
4. **Record the `investigation`.** Write the evidence substrate — the reproduction (or,
   where reproduction is not stable, what was observed and why), the avenues walked, and
   the observations gathered, each as a **re-verifiable fact, not a verdict** ("the value
   at `f():120` is already null", not "the cache is not the cause"). This persists the
   pre-work whether or not the cause grounds, and does not advance the phase.
   `telec todo artifacts write {slug} investigation <content>`.
5. **Conclude — or escalate.** If a causal root cause grounds, write the thin
   `diagnosis`: `## Symptom` (referencing `input`) and `## Root Cause` (the causal
   mechanism, **referencing the `investigation`'s evidence** for each claim). A reader
   can follow the mechanism from symptom to origin through cited evidence — not just a
   file and a line. `telec todo artifacts write {slug} diagnosis <content>`. If the cause
   will **not** ground, do not write a `diagnosis` and do not advance — escalate per
   Recovery.
6. **Advance.** Once the `diagnosis` is written, call `telec todo prepare {slug}`. The
   state machine derives `PLAN_DRAFTING` next; the planner consumes the root cause and
   derives the fix, and the plan reviewer validates that the root cause is a genuine
   causal mechanism grounded in the investigation.

## Outputs

- An `investigation` artifact (reproduction, avenues walked, observations as
  re-verifiable facts) — the durable evidence substrate.
- A `diagnosis` artifact (thin conclusion: causal mechanism referencing the
  investigation), written only when the cause grounds, consumed by the plan and
  validated at plan-review.
- No fix or verification prescription, no code changes, no worktree commits — the cause
  is grounded; the planner owns the fix.

## Pre-completion checklist

- The `investigation` records the reproduction (or why it is unstable) and the avenues
  walked, each observation a re-verifiable fact rather than a verdict.
- The `diagnosis` root cause names the causal mechanism — where the bad value or state
  originates, not where the symptom surfaces — and references the investigation's
  evidence for its claims.
- The `diagnosis` carries only `## Symptom` and `## Root Cause`; it prescribes no fix and
  no verification.

## Discipline

The failure this phase exists to prevent is the diagnosis that restates the symptom and
calls it done — naming where the error surfaces instead of why it originates — and the
diagnosis that reaches past its job to prescribe a fix. Both let an unverified or
symptom-shaped premise flow into planning, producing "delivered yet ineffective" fixes
and fallback-shaped workarounds. Slides to refuse: (1) accepting a located symptom as a
root cause; (2) prescribing a fix or verification approach here — diagnosis grounds the
cause, the planner decides the fix; (3) writing a conclusion not grounded in the recorded
investigation; (4) writing a "likely" cause to keep moving when the mechanism will not
ground — escalate instead; (5) diagnosing past a duplicate — investigating or writing
artifacts into a todo whose defect a further-along sibling already owns, instead of
triaging first (Step 1), retiring the twin, and ending; (6) diagnosing past a
high-confidence expected or won't-fix signal that should be suppressed or simply removed
before artifacts exist; (7) adopting a fix-shaped input's premise — a diagnosis whose
root cause is "the proposed capability is missing" restates the reporter's solution, not
a cause, and when that solution is a process change it smuggles an unratified process
decision into the lifecycle (`software-development/policy/process-change-authority`) —
re-derive the symptom and trace the mechanism, or escalate. A retired duplicate or
no-fix todo earns no artifacts. Escalation
is the strong, honest move: a "likely" cause is imagined confidence, and dressing it as a
finding to keep the pipeline moving is the cardinal sin this phase stops. The diagnosis is
judged by the cross-model plan reviewer; write it to be refuted, not to look right.

## Recovery

A root cause that will not ground is the trigger to escalate, never to proceed. No path
advances an ungrounded or symptom-shaped diagnosis. The `investigation` (Step 3) is
already written, so the trail is durable — escalation hands it forward, it is not lost.

1. **Dispatch one independent diagnoser.** Start a single cross-model peer session on a
   different model (`telec sessions start --agent <other> --path <path> --message
"<brief>"`), pointed at `telec todo artifacts read {slug} investigation` and the
   `input` symptom. Brief it to **re-verify the recorded observations rather than trust
   them** (they are leads, not verdicts — the upstream-is-a-hypothesis stance in
   `preparation-artifact-quality`), reach its **own** root cause, and **report its
   assessment as session output — write no artifact.** The peer sees the evidence but no
   conclusion (none is grounded), so its conclusion stays independent while redundant
   search is avoided.

2. **Reconcile.** Fold the peer's new evidence into the `investigation`. Read its
   assessment against your own, treating your prior thinking as the **prime suspect**,
   not the baseline. Take one more investigation pass with the combined awareness.
3. **Ground and proceed, or escalate and stop.** If the cause now grounds, write the
   `diagnosis` (referencing the investigation) and advance. If it still will not ground,
   **escalate to the human and stop** — the `investigation` is the union-of-trails
   artifact they open; no separate hand-off is needed. Do not fabricate a cause and do
   not advance an ungrounded diagnosis.

- If investigation shows the reported behavior is correct (not a defect), record that in
  the `investigation` and surface it; the bug may need reclassification or closure rather
  than a fix.
- If the grounded root cause is a **process-design gap** — removing it would require a
  behavioral delta to a process-layer contract — the bug lane does not plan that fix.
  Write the `diagnosis` (the cause is still the cause), then escalate per
  `software-development/policy/process-change-authority`: package the implied process
  delta for human decision and go idle. The bug either fixes what is fixable within the
  existing contract or holds pending the human's call.
- If that correct-behavior signal is a recurring log-hunter source that would keep
  re-filing, register a suppression so it stops: author the invariant pattern, run
  `telec bugs suppress "<pattern>" --reason "<why>" --source-bug {slug}`, record it in
  the `investigation`, and retire the todo. This replaces keeping a bug open
  indefinitely to suppress re-filing.

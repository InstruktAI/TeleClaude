---
description: Bug diagnosis phase. The driving session triages and records the investigation; a dispatched author owns the causal conclusion over that evidence. Two owners, two artifacts, one phase — diagnosis grounds the cause and prescribes no fix.
needs_domain_baseline: true
visibility: public
---

# Bug Diagnose — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/debugging.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md

## Goal

For a `bug`, produce a **verified root cause** before any fix is planned or written, in
two artifacts owned by two different contexts:

- **`investigation`** — the evidence substrate: the reproduction, the avenues walked,
  the observations gathered as re-verifiable facts, the live alternative hypotheses, and
  the causal frontier where the trace stops. Owned by the driving preparation session.
  Written whether or not a cause grounds.
- **`diagnosis`** — the thin conclusion: the causal mechanism (_why_ the code produces
  the wrong behavior) traced to the specific code where the bad value or state
  originates, grounded in and referencing the `investigation`. Owned by a dispatched
  author that did not gather the evidence. Written only once the cause grounds.

The two artifacts already order evidence before conclusion; the phase uses that order to
select different cognitive owners. It adds no review phase, no verdict, and no findings
artifact. Plan review remains the later cause-to-fix backstop.

Diagnosis grounds the cause and stops there. Neither owner opens a worktree, writes
production code, commits, or **prescribes a fix or verification approach** — the planner
decides the fix that removes the cause, and the builder writes it during `/next-build`.
A diagnosis that reaches for a fix has shifted its objective from _understand_ to
_alleviate_, and an objective of alleviation never reliably reaches cause.

## Preconditions

- `kind == bug`, and the todo is at the `INVESTIGATE` or `DIAGNOSE` lifecycle phase.
- `telec todo artifacts read {slug} input` exists with the reported symptom and discovery
  context.
- Which owner acts is derived from artifact presence: absent `investigation` routes the
  investigator inline; present `investigation` with absent `diagnosis` dispatches the
  diagnosis author.

## Steps

### The investigator — inline, driving session

0. **Read the creation record first.** `telec todo show {slug}` exposes `entry_point`,
   `lineage`, `human_involved`, and `context` — which door filed this bug, whose hands
   acted, and whether a human observed the symptom. A human-door filing (`tui`/`cli`/`web`)
   means the reported symptom is a first-hand human observation; an agent-initiated filing
   (`human_involved=false`) means the organic trigger lives in that agent's session
   evidence, and the investigation traces it there rather than manufacturing a synthetic
   reproduction as a silent stand-in. When a reproduction must be constructed, the
   investigation labels it synthetic and either traces the organic path or records the
   organic trigger as untraced — an explicit open gap, never an implied equivalence.

1. **Triage for duplicate, suppression, or no-fix — before any investigation or artifact
   write.** Simultaneous log scans and human reports produce near-coincident reports of
   the same defect, each scaffolding its own bug todo. The report-time moment cannot catch
   this — each reporter checks before the other's todo exists — but by the time this phase
   runs the sibling already exists, so the triage lives here, ahead of the investigation
   and every artifact write. Read this todo's reported symptom for the comparison
   (`telec todo artifacts read {slug} input`), list the in-flight bugs (`telec bugs list`,
   `telec todo list`), read the active suppression ledger (`telec bugs suppressions`), and
   read the `input` of the candidates that look related. A **duplicate** is another bug
   todo whose reported defect shares the same root symptom — the same error signature, the
   same failing surface — not merely the same file or area; that judgment is yours to make
   from the symptoms, not a string match. Reading inputs and suppressions is the triage's
   own work; the hard gate is on investigation and artifact writes, never on the read the
   triage depends on.
   - **If a sibling for the same defect is already in flight, retire this todo as the
     duplicate.** Resolve the race deterministically so two simultaneous sessions never
     both retire themselves: the **survivor** is whichever twin is already further along
     (has an `investigation`/`diagnosis` or an active session in this phase); when both
     sit at the same fresh state, the survivor is the **earliest-created** todo, tie-broken
     by lexically-first slug. If this todo is not the survivor, remove it —
     `telec todo remove {slug}`, naming the surviving slug in the reason — and **end the
     session**. Write **no** `investigation` and **no** `diagnosis`.
   - **Hand forward material info — only when sure it helps.** Before removing, compare
     this twin's `input` against the survivor's todo. If this twin carries discovery
     context the survivor does not surface — a distinct reproduction, a second occurrence
     site, an environment detail — and you are **confident it is genuinely additive**, send
     a single informational message to the survivor's active session
     (`telec sessions send <session_id> "<info>"`) before retiring. Substance only: no
     acknowledgement, no echo, no narration. If you are not sure it adds, stay silent and
     just retire.
   - **If the reported signal matches an active suppression, retire this todo as
     already-triaged.** A log-hunter signal already in the project's suppression ledger
     (`telec bugs suppressions`) was deliberately accepted as expected or won't-fix; treat
     it like a duplicate — remove the todo (`telec todo remove {slug}`, naming the
     suppression in the reason) and end the session, writing no artifacts.
   - **If the reported signal is itself a suppression or no-fix candidate, decide that
     before investigating.** Log-hunter bug reports sometimes describe correct operational
     behavior rather than a defect: external service throttles, stale duplicate cleanup,
     intentionally tolerated platform limits, or a report whose symptom was already fixed
     by a committed change. Do a short confirmation from the `input`, the active
     suppressions, and a targeted log check if needed; do not perform full investigation
     merely to prove an accepted no-fix classification. If the signal is a stable recurring
     condition that should not re-file, register the invariant pattern with
     `telec bugs suppress "<pattern>" --reason "<why>" --match regex --disposition
<expected|wontfix> --source-bug {slug}`, then remove the todo and end the session. If the
     signal was already fixed, one-off, or unlikely to recur, remove the todo and end the
     session **without** adding a suppression. If confidence is not high, keep the todo and
     continue; the cost of a false suppression is hiding a real bug.
   - **If this todo is the survivor, or no sibling exists, continue.**

2. **Read the symptom as a defect to investigate.** With the `input` already in hand from
   triage, treat it as a real, reproducible defect until investigation proves otherwise
   (refuse bug-denial).
   **Triage a fix-shaped input.** When the `input` names a missing capability or a solution
   rather than an observed wrong behavior ("X has no way to do Y", "add Z"), re-derive the
   symptom from evidence — the observable wrong behavior that prompted the report — and
   investigate that. The embedded solution is an unratified suggestion; it carries no
   authority into the investigation, the diagnosis, or the plan
   (`software-development/policy/process-change-authority`).

3. **Investigate.** Follow the systematic debugging procedure — reproduce first, then
   bisect and isolate. Read the actual code paths; do not pattern-match a likely cause.
   **Trace the cause, not the location:** trace backward from where the symptom surfaces
   toward where the bad value or state **originates**. Naming where the error is _thrown_
   or _observed_ is a restatement of the symptom located in code.

4. **Write the `investigation` and stop.** The handoff criterion is not that the evidence
   is sufficient for a root cause — deciding that is the same act as concluding one, and it
   belongs to the other owner. The criterion is a handoff-ready evidence substrate
   containing:
   - the organic trigger and creation context;
   - reproduction status, including whether any reproduction is synthetic;
   - a backward trace from the observed symptom as far as current evidence supports;
   - observations stated as re-verifiable facts with their source ("the value at `f():120`
     is already null", not "the cache is not the cause");
   - live alternative hypotheses, and the observations that falsify any rejected one;
   - the causal frontier: where the trace stops, what remains unknown, and which
     observation would discriminate the remaining explanations.

   `telec todo artifacts write {slug} investigation <content>`. A privately suspected cause
   creates no authority and is not written as the conclusion. Then call
   `telec todo prepare {slug}`; the state machine dispatches the diagnosis author.

### The diagnosis author — dispatched, independent

The dispatched session owns the causal conclusion. It is an artifact author, not a
reviewer of an already-authored diagnosis. Its order of work is load-bearing:

1. **Form an independent frame first.** Read the reported symptom and the creation context.
   Enter the code through your own path and build your own candidate causal map. Do not
   read `investigation` yet, and do not force an early verdict.
2. **Then read `investigation` as leads, not as the search boundary.** Re-verify its
   observations against the code rather than adopting them, and inspect the causal frontier
   for levels it never reached.
3. **Extend the evidence where necessary.** Preserve prior material and its provenance; do
   not silently replace the investigator's trail.
4. **Question the investigator only after your own pass**, where its account, evidence, or
   causal horizon needs clarification. Its answer is a claim to test, not truth to adopt.
   This is one bounded exchange, not an open polling loop.
5. **Write the thin `diagnosis` only when one causal mechanism grounds from symptom to
   origin.** It carries `## Symptom` (referencing `input`) and `## Root Cause` (the causal
   mechanism, referencing the current investigation evidence for every claim). A reader can
   follow the mechanism from symptom to origin through cited evidence — not just a file and
   a line. `telec todo artifacts write {slug} diagnosis <content>`. Prescribe no fix.

A plausible cause is not a diagnosis. If the cause will not ground, take the unresolved
path in Recovery.

### Shared evidence, one writer at a time

`investigation` is shared evidence and must not become a last-writer-wins document. Exactly
one party holds the write turn at any moment, and the slug's live claim is what names it:
the artifact-write boundary refuses a writer that is not the live claimant
(`project/spec/feature/workflow/artifact-versioning`, § Write authority).

- The driving session holds the claim while it writes the first-pass investigation.
- Dispatching the diagnosis author transfers the claim to that session, which excludes the
  driver for the duration and admits the child's writes.
- When the child needs the driver to gather evidence, the child asks and stops writing; the
  driver appends and reports completion; the child rereads the latest version before
  continuing.
- The claim returns to the driver when the child's session ends.

Version history preserves the sequence and the author identity of each write. It is a
record, not a merge mechanism: a writer rereads the latest version before each write rather
than reconciling divergent copies afterward.

### Advance

Once the `diagnosis` exists, the driving session calls `telec todo prepare {slug}`. The
state machine derives `PLAN_DRAFTING`; the planner consumes the root cause and derives the
fix, and the plan reviewer validates that the root cause is a genuine causal mechanism
grounded in the investigation.

## Outputs

- An `investigation` artifact — reproduction, avenues walked, observations as re-verifiable
  facts, live alternatives, and the causal frontier — authored by the driving session.
- A `diagnosis` artifact — the thin causal conclusion referencing that evidence — authored
  by a session that did not gather it, written only when the cause grounds.
- No fix or verification prescription, no code changes, no worktree commits.

## Pre-completion checklist

- The `investigation` records the reproduction (or why it is unstable), the avenues walked,
  the live alternatives, and the causal frontier — each observation a re-verifiable fact
  rather than a verdict.
- The `diagnosis` root cause names the causal mechanism — where the bad value or state
  originates, not where the symptom surfaces — and references the investigation's evidence
  for its claims.
- The `diagnosis` carries only `## Symptom` and `## Root Cause`; it prescribes no fix and
  no verification.
- The two artifacts were written by different sessions.

## Discipline

The failure this phase exists to prevent is one confidently wrong problem frame selecting
the evidence, declaring the cause, and shaping the fix before any other intelligence has
formed a view. Independence that waits for the investigating session to doubt itself never
arrives, because confident error does not feel uncertain — which is why the split is
structural and not triggered by self-assessment.

Slides to refuse: (1) accepting a located symptom as a root cause; (2) prescribing a fix or
verification approach here; (3) writing a conclusion not grounded in the recorded
investigation; (4) writing a "likely" cause to keep moving when the mechanism will not
ground; (5) investigating or writing artifacts into a todo whose defect a further-along
sibling already owns; (6) diagnosing past a high-confidence expected or won't-fix signal;
(7) adopting a fix-shaped input's premise; (8) the investigator steering the conclusion —
through a verdict written as an observation, a hypothesis presented as settled, or a
handoff that names the answer; (9) the diagnosis author reading `investigation` first and
calling the result independent. A retired duplicate or no-fix todo earns no artifacts.

The diagnosis is judged by the cross-model plan reviewer; write it to be refuted, not to
look right.

## Recovery

### The cause will not ground

The diagnosis author writes no `diagnosis`. It preserves its verified additions and its
causal frontier in the `investigation`, records why no cause grounds, and stamps the
unresolved outcome — `telec todo stamp {slug} --diagnosis-unresolved --reason "<why>"` —
which holds the todo with an audited `diagnosis_unresolved` source. The hold is what stops
the phase from dispatching another author indefinitely: without it the driving session
would call the state machine again into the same phase and re-derive the same dispatch.

The held todo waits for its next legitimate owner. A human releases it
(`telec todo update {slug} --release`) once there is a reason the next attempt would land
differently — new evidence, a narrowed frontier, or a decision to reclassify or close. The
`investigation` is the union-of-trails artifact they open; no separate hand-off is needed.

### The reported behavior is correct

If investigation shows the reported behavior is not a defect, record that in the
`investigation` and surface it; the bug may need reclassification or closure rather than a
fix. If that correct-behavior signal is a recurring log-hunter source that would keep
re-filing, register a suppression so it stops: author the invariant pattern, run
`telec bugs suppress "<pattern>" --reason "<why>" --source-bug {slug}`, record it in the
`investigation`, and retire the todo. This replaces keeping a bug open indefinitely to
suppress re-filing.

### The cause is a process-design gap

If the grounded root cause is a **process-design gap** — removing it would require a
behavioral delta to a process-layer contract — the bug lane does not plan that fix. The
`diagnosis` is still written (the cause is still the cause), then the driving session
escalates per `software-development/policy/process-change-authority`: package the implied
process delta for human decision and go idle. The bug either fixes what is fixable within
the existing contract or holds pending the human's call.

---
description: Prepare-driver procedure for bug diagnosis. Triage before dispatch, challenge the peer-authored mechanism, and stamp only a settled or explicitly unresolved outcome.
visibility: public
---

# Bug Diagnose — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/domain-baseline-bundle.md
- @~/.teleclaude/docs/software-development/procedure/debugging.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md

## Goal

For a `bug`, drive an independent diagnosis to a **verified root cause** before any fix is
planned or written. The driving session triages the todo, dispatches the peer, interrogates
its artifact, and stamps the outcome; it never authors the diagnosis or investigates in
parallel.

- **`diagnosis`** — the reproduction, the avenues walked, the observations recorded as
  re-verifiable facts, and the causal mechanism those observations ground: _why_ the code
  produces the wrong behavior, traced to the specific code where the bad value or state
  originates. Investigation and conclusion are one act by one author.

The dispatched peer owns investigation and every artifact revision under
`software-development/procedure/lifecycle/prepare/diagnose-peer`. The driving session owns
only triage, dispatch, interrogation, and lifecycle stamps. This procedure is the driver's
contract; the peer procedure is the artifact schema's single owner.

Diagnosis grounds the cause and stops there. Neither session opens a worktree, writes
production code, commits, or **prescribes a fix or verification approach** — the planner
decides the fix that removes the cause, and the builder writes it during `/next-build`. A
diagnosis that reaches for a fix has shifted its objective from _understand_ to _alleviate_,
and an objective of alleviation never reliably reaches cause.

## Preconditions

- `kind == bug`, and the todo is at the `DIAGNOSE` lifecycle phase.
- `telec todo artifacts read {slug} input` exists with the reported symptom and discovery
  context. When the creating-session fidelity gate applies, the driving session has
  reconciled that complaint against the creating transcript before dispatch.
- A `diagnosis` carrying no current settled stamp means the phase is mid-exchange, not
  complete.

## Steps

### 1. Triage — the driving session, before any peer is dispatched

Simultaneous log scans and human reports produce near-coincident reports of the same
defect, each scaffolding its own bug todo. The report-time moment cannot catch this — each
reporter checks before the other's todo exists — but by the time this phase runs the sibling
already exists. Triage therefore runs here, ahead of the dispatch, so a twin never costs an
independent diagnosis.

Read this todo's reported symptom (`telec todo artifacts read {slug} input`), list the
in-flight bugs (`telec bugs list`, `telec todo list`), read the active suppression ledger
(`telec bugs suppressions`), and read the `input` of the candidates that look related. A
**duplicate** is another bug todo whose reported defect shares the same root symptom — the
same error signature, the same failing surface — not merely the same file or area; that
judgment is yours to make from the symptoms, not a string match.

- **If a sibling for the same defect is already in flight, retire this todo as the
  duplicate.** Resolve the race deterministically so two simultaneous sessions never both
  retire themselves: the **survivor** is whichever twin is already further along (has a
  `diagnosis` or a live peer in this phase); when both sit at the same fresh state, the
  survivor is the **earliest-created** todo, tie-broken by lexically-first slug. If this todo
  is not the survivor, remove it — `telec todo remove {slug}`, naming the surviving slug in
  the reason — and end the session. Dispatch no peer.
- **Hand forward material info — only when sure it helps.** Before removing, compare this
  twin's `input` against the survivor's. If this twin carries discovery context the survivor
  does not surface — a distinct reproduction, a second occurrence site, an environment
  detail — and you are **confident it is genuinely additive**, send a single informational
  message to the survivor's active session (`telec sessions send <session_id> "<info>"`)
  before retiring. Substance only: no acknowledgement, no echo, no narration. If you are not
  sure it adds, stay silent and just retire.
- **If the reported signal matches an active suppression, retire this todo as
  already-triaged.** A log-hunter signal already in the ledger was deliberately accepted as
  expected or won't-fix; remove the todo (`telec todo remove {slug}`, naming the suppression
  in the reason) and end the session.
- **If the reported signal is itself a suppression or no-fix candidate, decide that before
  dispatching.** Log-hunter reports sometimes describe correct operational behavior rather
  than a defect: external service throttles, stale duplicate cleanup, intentionally tolerated
  platform limits, or a symptom already fixed by a committed change. Do a short confirmation
  from the `input`, the suppressions, and a targeted log check if needed; do not commission a
  full diagnosis merely to prove an accepted no-fix classification. If the signal is a stable
  recurring condition that should not re-file, register the invariant pattern with
  `telec bugs suppress "<pattern>" --reason "<why>" --match regex --disposition
<expected|wontfix> --source-bug {slug}`, then remove the todo and end the session. If it was
  already fixed, one-off, or unlikely to recur, remove the todo without adding a suppression.
  If confidence is not high, keep the todo and dispatch; the cost of a false suppression is
  hiding a real bug.
- **Triage a fix-shaped input.** When the `input` names a missing capability or a solution
  rather than an observed wrong behavior ("X has no way to do Y", "add Z"), re-derive the
  symptom from evidence — the observable wrong behavior that prompted the report — and pass
  that to the peer. The embedded solution is an unratified suggestion carrying no authority
  into the diagnosis or the plan (`software-development/policy/process-change-authority`).

Otherwise, proceed to the dispatch.

### 2. Dispatch the peer — the driving session

Dispatch one cross-model peer for this phase, selecting the agent from
`general/concept/agent-characteristics` rather than a hardcoded name.

The slug's claim stays with the driving session throughout. The peer writes `diagnosis`
under a dispatch lease opened for it at dispatch: for that lease's life, and for that
artifact only, the write boundary admits that session and refuses every other caller —
the driving session included, despite its standing claim
(`project/spec/feature/workflow/artifact-versioning`, § Write authority). The single
writer is enforced at the boundary rather than left to the driver's restraint. A lapsed lease refuses the write, and the peer stops writing
rather than writing unnoticed.

Brief it with the reported symptom and the creation context, and with nothing that names a
cause. The driving session holds no causal authority here, and a dispatch that arrives
carrying a suspected mechanism has already decided what the peer will find. Candidate
commits fall under the same prohibition: hand over the symptom and the evidence, and leave
the history unframed.

### 3. The interrogation — the driving session tests the written mechanism

A written `diagnosis` is not yet settled. The burden of proof is the peer's: it must convince
the driving session from the artifact and from targeted answers. The driver is a skeptical
examiner, not a competing diagnostician — it does not re-run the investigation, and a driver
that diagnoses in parallel has spent a second session to buy back the framing this phase
exists to separate.

Interrogate in this order:

1. **Find the weakest or largest jump in the causal chain**, and put it under the question
   below rather than accepting the chain as a whole.
2. **Ask which observation _proves_ that transition** rather than merely fitting it. Evidence
   compatible with the claim is not evidence for it; the question is what the observation
   rules out.
3. **Ask why the trace stops at the claimed origin** rather than at an upstream cause. A
   stopping point that reflects where the investigation began, rather than where the system
   boundary is, is the most common way a located symptom passes as a mechanism.
4. **Challenge horizontal completeness.** When the claimed origin is a shared contract, ask
   which producers, entry paths, and consumers implement it and what evidence accounts for
   each one. An unexplained sibling path means the root is not settled, even when the vertical
   causal chain for the reproducing path is sound.
5. **Ask for the strongest rival explanation and the observation that separates it** from the
   claimed one. A `diagnosis` whose alternatives section is empty owes a reason, not silence.
6. **Missing evidence is the peer's to gather.** Name the gap and return it; do not go and
   close it yourself. Investigating on the peer's behalf rebuilds the single-frame failure
   from the other end.
7. **The peer keeps the pen.** Every revision is written by the peer. The driving session
   never authors this artifact, at any point in the exchange.

**An answer is not an endpoint.** Each answer becomes the next claim under attack. A
restatement, a circular explanation, or a merely plausible account is challenged again, and
the drill continues until every transition **bottoms out in independently auditable
observation** — one whose provenance a third party can inspect and whose inference they can
evaluate without trusting its author. Auditable is not the same as repeatable: a race, a
historical incident, or a timing failure may never reproduce, and its limits are stated
rather than disqualifying it.

**Existing evidence may answer a challenge.** The artifact often already carries what the
question asks for, and demanding a fresh check every time turns interrogation into ceremony.
What matters is that the answer bottoms out, not that it is new.

**The peer may attack the interrogation.** A question can assume the wrong boundary, or
contradict evidence already recorded. The peer says so and shows it, and that answer is then
interrogated like any other. The driver's authority over the lifecycle is never authority
over the argument.

### 4. Settle and advance — the driving session

Settle when two conditions hold, both readable from the artifact rather than from either
party's confidence: **every causal transition is evidenced**, and **the strongest rival no
longer explains the observations**. Conviction is the judgment that applies that standard; it
is never the standard itself, which is why a plan reviewer can re-run it later against the
same text.

Stamp the settled cause: `telec todo stamp {slug} --diagnosis-settled`. The stamp binds to
the artifact's current digest, so a later revision invalidates it and the cause must be
settled again.

Then call `telec todo prepare {slug}`. The state machine derives `PLAN_DRAFTING`; the planner
consumes the root cause and derives the fix.

Plan review then applies the same standard again, and that is depth rather than repetition:
this phase tests the cause while there is still no plan to defend, and plan review both
catches what the interrogation missed and validates the derivation from cause to fix — which
does not exist yet here and so cannot be tested here.

An interrogation that cannot reach those two conditions is not resolved by the driver's
authority. It is the unresolved outcome in Recovery.

### Pre-completion checklist

- The root is the earliest violated contract within the stated system boundary, and the trace
  accounts for why comparable non-failing cases are not caught by it.
- A shared-contract root carries an evidence-backed census of every producer, entry path, and
  consumer within the system boundary; no sibling implementation is left unexplained.
- Every causal transition cites the observations that carry it, names what would falsify it,
  and bottoms out in independently auditable observation. Repeatability limits, where they
  exist, are stated rather than hidden.
- The reproduction is recorded, or the reason it is unstable, and any synthetic reproduction
  is labelled with its gap from the organic path.
- Observations are stated apart from their interpretation, and superseded entries are marked
  rather than deleted.
- The strongest credible rival is named, the check that separates it was run, and its result
  is recorded — or the absence of a rival carries a reason.
- Provenance carries one of the three verdicts with that verdict's evidence: a named commit
  and its diff hunk for Regression; both the introducing and the reachability change for
  Latent; the files, range, and search terms actually covered for Provenance not established.
  Any sibling damage a named commit reveals is recorded for its own triage, never folded into
  this fix (`software-development/procedure/debugging`, step 5).
- The root cause states its minimal causal set and its counterfactual, and prescribes no fix
  and no verification approach.
- Every version of the artifact carries the dispatched peer as its principal.
- The Attack record names the transitions challenged and the evidence that resolved each.
- Status matches reality, and the settled stamp is current for the artifact's digest.

## Outputs

- A `diagnosis` artifact — symptom, evidence as re-verifiable facts, and the causal mechanism
  they ground — authored by a dispatched peer at every revision, and settled by a stamp the
  driving session applies once the two align.
- No fix or verification prescription, no code changes, no worktree commits.

## Discipline

The failure this phase exists to prevent is one confidently wrong problem frame selecting the
evidence, declaring the cause, and shaping the fix before any other intelligence has formed a
view. Independence that waits for the driving session to doubt itself never arrives, because
confident error does not feel uncertain — which is why authorship moves and the challenge is
structural rather than triggered by self-assessment.

Slides to refuse: (1) accepting a located symptom as a root cause; (2) prescribing a fix or
verification approach here; (3) asserting a cause the recorded evidence does not carry;
(4) writing a "likely" cause to keep moving when the mechanism will not ground; (5)
dispatching past a duplicate or a high-confidence expected or won't-fix signal; (6) adopting
a fix-shaped input's premise; (7) briefing the peer with a suspected cause, which decides
what it finds before it looks; (8) tracing one reproducing path vertically while leaving
sibling implementations of the same contract horizontally unexamined.

The interrogation has failure modes of its own. The peer folds because the driver dispatched
it, advances the machine, and can end it — agreement bought by standing rather than evidence,
which is why settlement is measured against the artifact and not against either party's
sense of being done. The driver presses its own mechanism until the peer writes it down, at
which point the driver has authored the conclusion through another session's hands. Or the
driver stops early, because a chain that reads well is easy to accept and every further
question costs a round.

The opposite mistake is also real: a driver that misreads the boundary can drill a sound
chain toward `Unresolved`. The peer's licence to attack the interrogation is the counterweight
— and the outcome is not a failure. An unresolved bug reaches a human with both positions and
the observation that would separate them, which is a better artifact than a settled one that
was never tested.

The diagnosis is judged again by the cross-model plan reviewer; write it to be refuted, not
to look right.

## Recovery

### No cause grounds, or the disagreement is evidenced and persistent

Two outcomes take this path: no mechanism grounds for the peer at all, or a mechanism is
written and the interrogation reaches neither settlement condition. Both end the same way,
because an unsettled cause and an absent one are equally unsafe to plan against.

Persistent disagreement is an outcome, not a deadlock to break. Where both positions rest on
evidence and neither dislodges the other, the artifact records **both**, with the observation
that would separate them. A false `Unresolved` costs a human's attention; a false `Settled`
costs a plan, a build, and a fix aimed at the wrong cause — so the cheaper error is the one
this path takes. Settlement is never reached by conversational exhaustion, and the driver's
lifecycle authority breaks no tie.

The peer records in `diagnosis` what it verified, what remains contested, and which
observation would separate the rival mechanisms; its Status reads `Unresolved`. The driving
session stamps the outcome — `telec todo stamp {slug} --diagnosis-unresolved --reason "<why>"`
— which holds the todo with an audited `diagnosis_unresolved` source and leaves no settled
stamp, so the artifact cannot be mistaken for a conclusion the plan may consume. The hold is
what stops the phase from dispatching another peer indefinitely: without it the driving
session would call the state machine again into the same phase and re-derive the same
dispatch.

The held todo waits for its next legitimate owner. A human releases it
(`telec todo update {slug} --release`) once there is a reason the next attempt would land
differently — new evidence, a narrowed frontier, or a decision to reclassify or close. The
`diagnosis` is the artifact they open; no separate hand-off is needed.

### The reported behavior is correct

If the peer finds the reported behavior is not a defect, it records that in `diagnosis` and
reports it; the driving session surfaces it, and the bug may need reclassification or closure
rather than a fix. If that correct-behavior signal is a recurring log-hunter source that would
keep re-filing, register a suppression so it stops: author the invariant pattern, run
`telec bugs suppress "<pattern>" --reason "<why>" --source-bug {slug}`, record it in the
`diagnosis`, and retire the todo. This replaces keeping a bug open indefinitely to suppress
re-filing.

### The cause is a process-design gap

If the grounded root cause is a **process-design gap** — removing it would require a
behavioral delta to a process-layer contract — the bug lane does not plan that fix. The
`diagnosis` is still written and settled (the cause is still the cause), then the driving
session escalates per `software-development/policy/process-change-authority`: package the
implied process delta for human decision and go idle. The bug either fixes what is fixable
within the existing contract or holds pending the human's call.

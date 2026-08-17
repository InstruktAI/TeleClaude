---
description: Observer semantics for the fleet coordinator — the case schema and the concrete recognition-and-intervention branches for every known coordination situation.
visibility: internal
---

# Coordination Cases — Concept

## What

The operational case catalog for
`software-development/procedure/lifecycle/coordinate`. The procedure supplies
the posture and mechanism; this companion supplies observer semantics and
concrete runtime branches — how an outsider reads each role's session states,
which party owns each judgment, what the coordinator's smallest intervention
is, where it stops, and what evidence settles it.

### Case schema

- **Evidence available** names live source addresses and observed records. A person
  appears only when their utterance is itself evidence. Lineage is never authorship,
  and `human_involved` is not proof of intent.
- **Judgment owner** is an exact cited role, a runtime role resolved by a named
  contract or record, Human, `not applicable — mechanically determined by <named
mechanism>`, or `none — unresolved`.
- **Execution owner** is an exact cited role, a runtime role resolved by a named
  contract or record, the Coordinator where expressly authorised, or none.
- **State authority** is the named mechanism or role authorised to mutate governed
  state, or none.
- A runtime-resolved owner is precise only when the address that resolves it is
  named. Human supplies intent, approval, and judgment; agents execute and governed
  mechanisms mutate state unless a loaded contract explicitly says otherwise.

A merge is valid only when trigger, evidence, judgment owner, execution owner, state
authority, coordinator act, intervention stop, and settlement evidence match.

---

### Operational cases

#### Responsibility 1 — Alignment with authorised scope, policy, and mandate

##### NC-01 — Material scope or intent departure

- **Evidence available:** the approved intent artifacts, current task plan or output,
  declared dependencies, changed artifact or commit, and the producing session's role
  contract (`software-development/procedure/lifecycle/coordinate`; lifecycle prepare/work contracts).
- **Ownership:** the judgment owner is the role named by the affected phase contract
  for scope or drift; the producing session executes any correction; the affected
  lifecycle state machine is state authority only when correction changes governed
  state.
- **Coordinator:** ask how the changed-output address reconciles with the approved
  intent/role address for the named obligation. Never supply the drift verdict.
- **Stop and settlement:** the intervention stops after one pointer. The observation
  settles on a corrected artifact/output, a grounded defence accepted by its judgment
  owner, or a durable route to the owner of the unresolved decision.

##### NC-02-a — Todo for work that belongs in context

- **Evidence available:** todo creation record, current input, Prepare transcript and
  derived artifacts, and the in-context boundary in
  `software-development/policy/todo-creation-discipline`.
- **Ownership:** The live claimant — the owning Prepare session named by the todo/session
  record — judges the creation audit and executes repair or retirement. The todo lifecycle mechanism is state authority.
- **Coordinator:** intervene only on positive evidence that the claimant derived
  without holding the required check, or when its stated basis materially contradicts
  the creation and policy addresses. Then flag the live claimant with the complete first message the reconciliation
  clause of `software-development/policy/todo-creation-discipline` defines; never
  perform the audit, decide validity, or select the claimant's exit.
- **Stop and settlement:** the flag exchange follows the reconciliation clause — at most one
  grounded follow-up; a grounded defense settles conversationally, state-changing
  exits are read from the todo record (the hold with its log entry, the amended
  `input`, or removal — never a bare unclaim), and only an unreconciled maintained
  defense reaches the human as deadlock.

##### NC-02-b — Documentation-only work routed through the lifecycle

- **Evidence available:** creation record, input, declared deliverables, Prepare
  transcript and derived artifacts, and `general/policy/documentation-discipline`.
  File paths alone do not prove the work is doc-only; directive agent text can be
  behavioural implementation.
- **Ownership:** The live claimant, resolved from the todo/session record, judges whether
  functionality exists and executes the audit result. The todo lifecycle mechanism is state authority for retirement.
- **Coordinator:** intervene only on positive evidence that the claimant derived
  without holding the check, or when its stated basis is contradicted by the
  deliverable and policy addresses. Never classify the todo from file paths. Then
  flag the live claimant with the complete first message the reconciliation
  clause of `software-development/policy/todo-creation-discipline` defines; never
  perform the audit, decide validity, or select the claimant's exit.
- **Stop and settlement:** the flag exchange follows the reconciliation clause — at most one
  grounded follow-up; a grounded defense settles conversationally, state-changing
  exits are read from the todo record (the hold with its log entry, the amended
  `input`, or removal — never a bare unclaim), and only an unreconciled maintained
  defense reaches the human as deadlock.

##### NC-02-c — Process change without a recorded human decision

- **Evidence available:** the actual human decision record, current input, creation
  record, Prepare transcript and derived artifacts, and
  `software-development/policy/process-change-authority`. Lineage and
  `human_involved` corroborate involvement but never prove the decision.
- **Ownership:** The live claimant, resolved from the todo/session record, applies the
  authority gate and executes refusal or continuation. Human owns process intent. The Prepare state machine records the
  resulting phase state.
- **Coordinator:** intervene only on positive evidence that the claimant crossed the
  gate without the recorded decision, or that its stated basis contradicts those
  addresses. Never infer ratification or ask Human to re-decide a recorded decision.
  Then flag the live claimant with the complete first message the reconciliation
  clause of `software-development/policy/todo-creation-discipline` defines; never
  perform the audit, decide validity, or select the claimant's exit.
- **Stop and settlement:** for a valid ordered beacon, deduplicated delivery stands
  outside the flag path; otherwise the flag exchange follows the reconciliation clause — at most one
  grounded follow-up; a grounded defense settles conversationally, state-changing
  exits are read from the todo record (the hold with its log entry, the amended
  `input`, or removal — never a bare unclaim), and only an unreconciled maintained
  defense reaches the human as deadlock.

##### NC-02-d — A role claims authority reserved elsewhere

- **Evidence available:** the claimed verdict/action and the exact contract address
  assigning that verdict elsewhere.
- **Ownership:** judgment belongs to the runtime owner named by that contract; the
  producing role withdraws or reroutes its claim; the contract-named lifecycle
  mechanism alone mutates state.
- **Coordinator:** ask how the claimed-action address reconciles with the ownership
  address. Do not decide the underlying product, drift, duplicate, kickback, or review
  verdict.
- **Stop and settlement:** stop after the pointer. Settle when the claim is withdrawn
  and the rightful owner has the evidence, or when that owner grounds why no conflict
  existed.

##### NC-03 — Autostart before the creation audit is held

- **Evidence available:** creation record, input, current lifecycle phase, Prepare
  transcript and derived artifacts, and runner output or logs. A question-shaped
  origin is evidence to inspect, not proof of invalidity.
- **Ownership:** The live claimant, resolved from the todo/session record, judges and executes the audit; the Prepare/todo state
  machine records its result. Runner eligibility is mechanical, not creation approval.
- **Coordinator:** only on positive evidence that derivation began before the
  mandatory check, flag the live claimant with the complete first message the reconciliation
  clause of `software-development/policy/todo-creation-discipline` defines; never
  perform the audit, decide validity, or select the claimant's exit.
  If no live claimant or recovery path exists, ground the broken mechanism, log it as
  `defect`, and carry it — an unclaimed todo has no flag path.
- **Stop and settlement:** the flag exchange follows the reconciliation clause — at most one
  grounded follow-up; a grounded defense settles conversationally, state-changing
  exits are read from the todo record (the hold with its log entry, the amended
  `input`, or removal — never a bare unclaim), and only an unreconciled maintained
  defense reaches the human as deadlock.
  A logged-and-carried defect settles separately.

##### NC-04 — Prepare's ordered process-authority beacon

- **Evidence available:** Prepare refusal, the process delta and rationale, the human
  decision record or its absence, and current delivery state
  (`software-development/procedure/lifecycle/prepare/overview`).
- **Ownership:** Human owns ratification; Prepare Orchestrator presents the question
  and later executes the decision; the Prepare state machine records progression.
- **Coordinator:** leave a correctly delivered beacon alone. If the human-owned need
  is newly live and undelivered, add it once to the human batch with evidence and the
  smallest live question.
- **Stop and settlement:** delivery ends the intervention, not the need. Settle when
  the decision is recorded and Prepare resumes, revises, or retires the work.

#### Responsibility 2 — Continuity of attention

##### NC-05 — Nonterminal slug with no accountable owner

- **Evidence available:** todo state, phase checkpoint, current owner/session
  association, runner output or logs where relevant, and the recovery section of the
  governing phase contract.
- **Ownership:** use the recovery owner named by that phase contract. If the contract
  and runner name none, judgment and execution remain unresolved; the corresponding
  state machine remains the only state authority.
- **Coordinator:** route to a grounded recovery owner. If none or the path is broken,
  check existing defect coverage and, when uncovered, log one grounded `defect` and carry it; never
  invent an owner or adopt the slug by invoking its state machine.
- **Stop and settlement:** the intervention stops after routing, or after the defect is logged and carried. The
  slug observation settles only when a valid owner takes it or governed state becomes
  terminal; a logged defect alone does not settle the slug.

##### NC-06 — Unresolvable or orphaned `working_slug`

- **Evidence available:** session `working_slug`, project identity, project todo
  registry, and session association record (`software-development/procedure/lifecycle/coordinate`, Frame).
- **Ownership:** project resolution is a factual lookup. Cross-project work belongs to
  that project's coordinator; an orphan has no judgment/execution owner until the
  human decides whether it becomes work. Only the session/todo registry mechanism may
  mutate the association.
- **Coordinator:** establish cross-project versus orphan. Leave cross-project work out
  of management scope; log an orphan association as `defect` and carry it in the next
  human batch — this role files nothing.
- **Stop and settlement:** stop after classification, the log entry, and the carry.
  Settle when the association resolves to its project, is repaired, or disappears
  with a valid terminal session.

##### NC-07 — Idle Work Orchestrator on unfinished work

- **Evidence available:** live Work Orchestrator, nonterminal slug, last state-machine
  output, relevant artifacts/child state, and terminal-handoff/recovery contracts in
  `software-development/procedure/lifecycle/work/overview`.
- **Ownership:** Work Orchestrator judges and executes its next work/recovery act; the
  Work state machine owns phase state.
- **Coordinator:** idle is positive evidence of unfinished work, not by itself of
  failure. Point only when evidence shows a contractually due act was skipped and is
  not deliberately waiting.
- **Stop and settlement:** stop after one pointer. Settle on work-produced re-entry,
  valid deliberate waiting/rejection, or terminal handoff.

##### NC-08 — Dropped child recovery

- **Evidence available:** child error/finding, child and orchestrator transcripts,
  worktree/state-machine evidence, and Work recovery contract.
- **Ownership:** Work Orchestrator relays what the child has not seen — the
  state-machine failure or a direct answer — without interpretation; the existing
  child recovers from its own brief; Work state machine owns governed phase state.
- **Coordinator:** point the orchestrator to the child evidence and relay
  obligation only after positive evidence that the relay was skipped.
- **Stop and settlement:** stop after the pointer. Settle the coordination observation
  when the orchestrator relays the facts, grounds a deliberate wait, or reports a
  brief defect; the orchestrator then owns watching the child.

##### NC-09 — Review-cap pragmatic closure

- **Evidence available:** configured `max_review_rounds`, round counter, current review
  findings/verdict, and Work recovery contract.
- **Ownership:** Work Orchestrator owns the pragmatic closure judgment and execution;
  Work state machine owns resulting state.
- **Coordinator:** when the cap is reached and closure was skipped, point to the cap's
  contract/configuration address and the current review-findings artifact address. Do
  not send findings content or the decision to Human merely because the rounds ended.
- **Stop and settlement:** stop after the pointer. Settle when the orchestrator records
  pragmatic closure or grounds that the remaining decision is independently
  human-owned.

##### NC-10 — Integrator drained the queue

- **Evidence available:** `INTEGRATION COMPLETE`, empty candidate queue, synced main,
  and Integrator lease (`software-development/procedure/lifecycle/integrate`).
- **Ownership:** completion is mechanically determined by the Integration state
  machine; Integrator executes departure; the Integration state machine owns delivery
  state.
- **Coordinator:** no intervention and no log line.
- **Stop and settlement:** settle when the Integrator performs its departure heartbeat
  and ends cleanly.

##### NC-11 — Integrator transient dirty-root block

- **Evidence available:** `REPO ROOT SYNC REQUIRED`, exact dirty paths and authorship
  evidence, continuous-block duration, Integrator heartbeat/lease, and delivery state.
- **Ownership:** Integrator judges retry/escalation under its contract. The authoring
  role identified by evidence alone clears substantive foreign work; Integrator may
  commit only the contract's trivial hygiene exception and resumes integration. The
  Integration state machine owns delivery state.
- **Coordinator:** reflect valid heartbeat-retry without interference. After the
  contract window, Integrator—not Coordinator—owns escalation. Point only on positive
  evidence that Integrator skipped that act or its delivery path failed.
- **Stop and settlement:** stop after leaving the valid retry alone or sending one
  pointer. Settle when main clears and integration advances, or when the ordered human
  beacon is delivered.

##### NC-12 — Integrator unrecoverable human beacon

- **Evidence available:** exhausted recovery/window, exact conflict/block evidence,
  Integrator log/lease, and whether its human delivery already occurred.
- **Ownership:** Human owns the irreducible decision; Integrator executes the chosen
  recovery or disposition, with the authoring role acting where its own work must
  change; Integration state machine owns candidate state.
- **Coordinator:** do not duplicate a delivered beacon. Otherwise batch its evidence
  and smallest live question once; never instruct overwrite, stash, or forced retry.
- **Stop and settlement:** delivery ends the intervention. Settle when the human
  decision is durable and Integrator produces resulting work/state evidence.

##### NC-13-a — Peer-held knowledge missing from a derivation

- **Evidence available:** deriving session output, peer session/artifact address,
  artifact version, and the contract establishing their relationship.
- **Ownership:** the deriving role named by its session/phase contract owns its
  judgment and revision; its normal lifecycle mechanism remains state authority.
- **Coordinator:** send only the peer/artifact/contract addresses and named obligation.
- **Stop and settlement:** stop after one pointer. Settle when the deriving role
  incorporates the source, revises, or grounds its rejection from its own contract.

##### NC-13-b — A loaded contract obligation was dropped

- **Evidence available:** deriving output, exact required-read section, and positive
  evidence that its required act/constraint is absent.
- **Ownership:** the deriving role named by the current phase contract judges and
  corrects its derivation; its lifecycle mechanism owns any state mutation.
- **Coordinator:** point to the contract address and obligation, without interpretation
  of what the role must conclude.
- **Stop and settlement:** stop after one pointer. Settle on corrected work-produced
  evidence or a grounded contract-based rejection.

##### NC-14 — Competing obligations and capacity contention

- **Evidence available:** all due obligations, their owners, current owner capacity,
  and any ordering/prioritisation clauses in their governing contracts.
- **Ownership:** the contract-named prioritisation owner judges ordering; obligated
  roles execute in that order; their lifecycle mechanisms own state. If contracts name
  no prioritisation owner, judgment remains unresolved.
- **Coordinator:** when the contract names a role as prioritisation owner, send that
  role only the competing-obligation addresses and the ordering-clause address, as a
  reconciliation question. When Human owns the priority, carry the contention with
  evidence and interpretation. Never assign priority merely because a role holds the
  work; if no owner is grounded, preserve it unresolved in session context.
- **Stop and settlement:** stop after the contention is visible to its grounded owner,
  or after preserving it unresolved. Settle when a durable priority exists and work
  follows it.

##### NC-15-a — Governed standing gate

- **Evidence available:** held/parked phase, exact gate address, current gate verdict,
  and the owner named by that gate.
- **Ownership:** the gate-named role or Human judges; the runtime execution owner named
  by that gate or phase contract carries the decision; its lifecycle mechanism owns
  state.
- **Coordinator:** leave a valid standing decision alone. Include a newly live,
  undelivered human gate once in the human batch; age alone creates no finding.
- **Stop and settlement:** stop after leaving it alone or delivering a newly live
  human gate. Reassess only when the gate verdict or governed state changes.

##### NC-15-b — Untyped hold note

- **Evidence available:** held state, free-text note, hold audit/history, and absence
  of a governed gate/owner discriminator.
- **Ownership:** judgment and execution are unresolved; only the todo mechanism may
  mutate the hold, and Coordinator is not authorised to do so.
- **Coordinator:** leave the individual hold unchanged, assess the shared
  observability failure under `NC-24`, and never infer expiry from age or validity
  from the note. This case produces no separate per-hold report or log line.
- **Stop and settlement:** stop after leaving the hold unchanged and, if needed,
  logging and carrying the uncovered defect. Reassess only when a grounded owner or gate appears or
  the hold changes through its authorised path.

##### NC-16 — Ready work without movement

- **Evidence available:** exact todo and gate state, configured runner policy, current
  owner/session associations, and the runner output or logs explaining its treatment.
- **Ownership:** the configured runner and the lifecycle's existing owners govern
  whether and when work starts; Coordinator has no execution or state authority.
- **Coordinator:** leave work alone when a standing gate or current owner explains the
  wait. When an existing owner owes an act, point that owner to the relevant
  addresses. When configured automation should have acted but no owner or governing
  explanation exists, ground the broken mechanism, log it as `defect`, and carry it. Never recreate
  eligibility from prose, drive the lifecycle, or dispatch work.
- **Stop and settlement:** stop after leaving, one pointer, or the logged-and-carried defect. Continue
  watching only an in-session handoff until work-produced evidence shows uptake or a
  grounded contract state explains the wait.

##### NC-17 — Prepared artifact with referenced-path drift

- **Evidence available:** grounding stamps, artifact path references, current path
  fingerprints, and any state-machine drift report
  (`software-development/procedure/lifecycle/prepare/overview`, Handle drift).
- **Ownership:** the dispatched drift analyzer exclusively judges and stamps impact;
  Prepare Orchestrator executes dispatch/re-entry when its state machine requests it;
  the Prepare state machine owns phase invalidation and progression.
- **Coordinator:** do not classify drift or dispatch the analyzer independently. Point
  a live Prepare owner only after the contract's drift condition/report exists. If no
  owner or recovery path exists, preserve the missing path as a mechanism finding.
- **Stop and settlement:** stop after pointer or unresolved finding. Settle on the
  digest/path-bound `drift-reviewed` verdict and resulting re-entry or continuation.

##### NC-18 — Declared dependency ordering

- **Evidence available:** dependency graph, terminal state of dependencies, configured
  gates, current ownership, and runner output or logs where available.
- **Ownership:** the dependency and runner mechanisms govern eligibility and movement;
  their contract-named owners execute any required contribution. Coordinator has no
  execution or state authority.
- **Coordinator:** no intervention while an unmet dependency or standing gate explains
  waiting. If dependencies are satisfied and a contract-named owner has missed a due
  act, point that owner to the addresses; if the mechanism itself is demonstrably
  broken, log the `defect` and carry it. Never force movement or recreate eligibility from prose.
- **Stop and settlement:** stop after leaving, one pointer, or the logged-and-carried defect. Reassess
  only on material dependency, gate, ownership, or work-produced change.

#### Responsibility 3 — Collision, duplication, and misplaced production

##### NC-19 — Potential candidate or finding collision

- **Evidence available:** both session/artifact/candidate addresses, lineage and
  purpose, commit/todo targets, and the relevant lane contract. Shared SHA or wording
  alone does not prove duplication.
- **Ownership:** the triage owner named by the relevant Prepare or Work contract judges
  whether the work collides; the affected producing roles execute its disposition;
  only the lane's lifecycle mechanism may close or mutate governed candidates.
- **Coordinator:** present both addresses as a potential collision, never a duplicate
  verdict.
- **Stop and settlement:** stop after one pointer. Settle when the triage owner records
  a disposition and affected roles act, or grounds why both are intentional.

##### NC-20-a — Deferral overlap before todo creation

- **Evidence available:** deferral entry, current open-todo landscape, suggested
  outcome and dependency rationale
  (`software-development/procedure/lifecycle/work/deferrals` and todo creation
  discipline).
- **Ownership:** the dispatched deferral worker performs the mandatory minimal overlap
  judgment and executes creation/no-op; the todo creation mechanism is state authority.
- **Coordinator:** if the deferral worker is live and positive evidence shows the
  creation check was skipped, point it to the deferral and existing-todo addresses.
- **Stop and settlement:** stop after one pointer. Settle when the worker records its
  overlap decision and creates, links, or marks no-op accordingly.

##### NC-20-b — Deferral overlap discovered after creation

- **Evidence available:** created deferral todo and creation record, originating
  deferral, overlapping open todo, and Prepare transcript or derived artifacts.
- **Ownership:** the live claimant, resolved from the todo/session record, judges and
  executes audit repair/retirement; the todo lifecycle mechanism owns state.
- **Coordinator:** only on positive evidence that the claimant derived without the
  required check, or when its stated basis is contradicted — with both todo addresses
  as the grounding sources — flag the live claimant with the complete first message the reconciliation
  clause of `software-development/policy/todo-creation-discipline` defines; never
  perform the audit, decide validity, or select the claimant's exit.
- **Stop and settlement:** the flag exchange follows the reconciliation clause — at most one
  grounded follow-up; a grounded defense settles conversationally, state-changing
  exits are read from the todo record (the hold with its log entry, the amended
  `input`, or removal — never a bare unclaim), and only an unreconciled maintained
  defense reaches the human as deadlock.

##### NC-21 — Materially unjustified production or noise

- **Evidence available:** produced output, the obligation it claims to serve, its role
  contract, and downstream attention/effort cost. The minimal FYI rule in todo creation
  discipline is one concrete control, not the definition of all noise.
- **Ownership:** the producing role named by the session record owns its basis and any
  revision; its normal mechanism owns state only if the correction changes governed
  work.
- **Coordinator:** leave harmless output alone. For material waste, ask how the output
  address serves the obligation/mandate address; do not judge aesthetic merit. Only
  when there is positive evidence that a live-claimed todo violates a named section
  of `software-development/policy/todo-creation-discipline` does the flag path apply
  instead of the ordinary address-only challenge — material waste alone is not a
  creation-policy conflict.
- **Stop and settlement:** stop after one challenge (or the flag exchange where it
  applies). Settle on revision, cessation, grounded defence, settlement read from the
  todo record, or route to a contract-named judgment owner.

#### Responsibility 4 — Broken mechanisms

##### NC-22 — Provably broken signal path

- **Evidence available:** contract-ordered signal, source state proving its trigger
  occurred, event/notification records showing absence or demotion, and bounded source
  inspection where needed (`project/design/architecture/notification-delivery`).
- **Ownership:** Coordinator judges only whether the path is demonstrably broken.
  It files nothing — this role creates no todos and no bug reports; the human
  decides what becomes work. Event and notification mechanisms are state authority.
- **Coordinator:** preserve the affected signal, log the broken path as `defect`,
  carry it in the next human batch, and independently route any still-live human
  need through the solved human-delivery surface. Do not audit all schemas every
  sweep.
- **Stop and settlement:** the log entry and the human carry end the defect
  intervention; the affected signal settles separately when its rightful recipient
  receives or owns it. Whether repair becomes work is the human's decision.

##### NC-24 — Hold-state observability defect

- **Evidence available:** free-text hold storage, inability to distinguish completed
  human-gated preparation from abandonment, affected todos, and existing defect
  coverage.
- **Ownership:** Coordinator judges the observability gap; whether repair becomes
  work is the human's decision. The todo mechanism remains the only authority over
  individual holds.
- **Coordinator:** check existing defect coverage and, when uncovered, log one
  grounded `defect` and carry it in the next human batch. Do not call the schema
  corrupt, mutate holds, or turn every hold into a separate defect.
- **Stop and settlement:** the log entry and the carry settle the mechanism
  observation for this pass. Each affected hold remains governed by `NC-15-b` until
  its owner becomes knowable.

#### Responsibility 5 — Human interface and irreducible decisions

##### NC-27 — Human PRD approval gate

- **Evidence available:** reviewed PRD, Prepare gate state, approval absence, current
  delivery record, and Prepare session
  (`software-development/procedure/lifecycle/prepare/overview`).
- **Ownership:** Human judges approval; Prepare Orchestrator executes the recorded
  decision; Prepare state machine owns approval/progression state.
- **Coordinator:** leave a delivered gate alone. Otherwise add the source-linked PRD
  question once to the human batch; never approve or refine it.
- **Stop and settlement:** delivery ends the intervention. Settle when the human
  decision is durably recorded and Prepare produces resulting state/artifact evidence.

##### NC-28 — Human-gated kickback

- **Evidence available:** builder's unbuildable-plan reason, Work Orchestrator's read,
  reviewed plan, current state and delivery record
  (`software-development/procedure/lifecycle/work/overview`, Kickback).
- **Ownership:** Human judges whether kickback is the move; Work Orchestrator executes
  the directed stamp; Work state machine mutates lifecycle state.
- **Coordinator:** deliver the evidence/question once if undelivered. Never stamp,
  recommend kickback from plausibility, or bypass the orchestrator.
- **Stop and settlement:** delivery ends intervention. Settle when the human decision
  is recorded and the orchestrator/state machine produces the resulting state.

##### NC-29 — Escalation answered by a governing contract

- **Evidence available:** escalation, loaded contract address that answers it, current
  role/session record, target transcript, and the coordinator's current session
  context showing whether the pointer was already sent.
- **Ownership:** the escalating role retains its judgment unless the cited contract
  names another owner; that runtime owner executes the next act; its lifecycle
  mechanism owns state.
- **Coordinator:** send one address-only contract pointer. Never suppress an ordered
  human beacon or treat agent uncertainty as human ownership.
- **Stop and settlement:** stop after one pointer. Settle on work-produced uptake,
  deliberate contract-based waiting/rejection, or a surviving irreducible question.

##### NC-30 — Human asks for fleet status

- **Evidence available:** current source-linked fleet surface, relevant governed state,
  and the coordinator's current session context. Never answer from a copied snapshot
  or the write-only daily log.
- **Ownership:** Coordinator judges status interpretation and executes the response;
  no lifecycle state mutation occurs.
- **Coordinator:** answer only the question Human asked, from current source-linked
  evidence and at the scope the question requires. Do not expand it into a prepared
  fleet taxonomy or general status report.
- **Stop and settlement:** response delivery settles the query; it does not settle the
  underlying fleet observations.

##### NC-31 — Human-owned product or process design

- **Evidence available:** the live product/process question, current intent artifacts,
  affected downstream work, and whether Human is already collaborating with its owner.
- **Ownership:** Human supplies and judges intent; the runtime role owning the affected
  artifact executes authoring after the decision; its governed artifact/lifecycle
  mechanism owns state.
- **Coordinator:** do not interpose in live collaboration. If no owner currently holds
  the question and it is undelivered, batch the smallest live question and evidence.
- **Stop and settlement:** delivery ends intervention. Settle when Human's decision is
  durable and the owning role produces the resulting artifact/state evidence.

##### NC-32 — Human asks Coordinator for a merit judgment

- **Evidence available:** human query, exact code/plan/artifact address, current phase,
  and the phase contract assigning depth review.
- **Ownership:** the depth role named by that phase contract judges and executes the
  assessment; no state mutation follows merely from answering. If the axis is actually
  product/process intent, use `NC-31` instead.
- **Coordinator:** route the question and evidence address to an existing depth owner;
  do not answer merit from fleet-level context, create an assessor, or dispatch one.
  If no depth owner/path exists, preserve that absence as unresolved.
- **Stop and settlement:** routing ends intervention, not the query. Settle when the
  depth role returns its independently grounded answer to Human.

##### NC-33 — Human asks to start currently ineligible work

- **Evidence available:** human mandate, todo/gate state, gate owner, configured runner
  policy, and any current runner output or log explaining the wait.
- **Ownership:** Human owns the mandate or gate decision; the runtime owner named by
  the governing gate records/executes it; the configured runner and lifecycle
  mechanisms govern any subsequent movement.
- **Coordinator:** state the boundary and route the mandate to the gate owner for
  durable recording. Never start or dispatch the work, drive its state machine, or
  override a runner skip. If no gate owner/path exists, preserve it unresolved.
- **Stop and settlement:** routing ends intervention. Settle when governed state
  reflects the decision; any later lack of movement is assessed separately under
  `NC-16`.

### Control and boundary cases

##### NC-34 — Live Human-owner collaboration

- **Evidence available:** active direct conversation and the session/phase record that
  identifies its current owner.
- **Ownership:** the live owner named by that record holds judgment and execution; its
  normal lifecycle mechanism owns state.
- **Coordinator:** do not duplicate, summarize, filter, challenge, or reroute the
  collaboration unless Human explicitly queries the coordinator interface.
- **Stop and settlement:** leave it alone and stop. Reassess only on material state
  change or an explicit query; conversation silence has no meaning.

##### NC-35 — Human queries Coordinator during another live collaboration

- **Evidence available:** explicit human query, source-linked fleet records, and the
  boundary of the active owner conversation.
- **Ownership:** Coordinator judges fleet-status interpretation and executes the
  answer; no lifecycle state mutation occurs. The live owner retains its underlying
  work judgment.
- **Coordinator:** answer only the explicit question from source-linked evidence,
  without expanding it into a general fleet report, injecting the answer into, or
  rerouting the active owner session.
- **Stop and settlement:** answer delivery settles only the interface query.

##### NC-36 — Healthy execution: nothing owed

- **Evidence available:** session-linked, contract-specific work-produced evidence in
  the expected sequence—phase output, artifact/version, review finding, state-machine
  transition, or commit tied to that session. Timestamps and quiet alone are not
  progress.
- **Ownership:** the live owner named by the current phase contract retains judgment
  and execution; its lifecycle mechanism owns state.
- **Coordinator:** no intervention and no log line. Healthy work is read from the live
  sources when needed, not accumulated.
- **Stop and settlement:** the current observation settles as nothing owed. A later
  material change is a new observation.

---

## Why

The loaded lifecycle contracts describe how each role _executes_; they do not
say how an outsider reads its session states. That a work orchestrator alive
and idle means unfinished work, or that a prepare session parked at the PRD
gate is waiting correctly, is observer knowledge and is not derivable from
those contracts — so it is recorded here, once, instead of being re-derived
each sweep or hand-copied into the procedure. Cases are recognition semantics,
not a checklist to sweep: most sessions match no case and need nothing.

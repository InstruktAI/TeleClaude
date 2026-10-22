---
description: The closed vocabularies of item phases and acts, who may perform each act, and how a backend-blind machine drives preparation and work from procedure headers through claim, spec, readiness, waiting and the owner's decision.
delivered_by: [issue-128]
---

# Item Lifecycle — Spec

## What it is

Preparation and work of a project's item run on one machine driven by the four v2 procedures. The machine reads and writes item state only through the workflow store port (`local/projects/teleclaude/design/architecture/workflow-store`) and routes by the capabilities the store declares, never by backend. Its design is `local/projects/teleclaude/design/architecture/workflow-machine`.

This spec owns the closed vocabularies of phases and acts. A store adapter or renderer carries these values and adds none; the machine accepts only them.

Facing: every actor below is an agent session unless a person is named. A person takes part by dropping in or by answering a question that is theirs.

## Canonical fields

### Phases

| Phase         | Meaning                                                                                                                                                                                                                                                                                                                                                                |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `preparation` | The item's spec is being written and challenged. Driven by the preparation driver.                                                                                                                                                                                                                                                                                     |
| `waiting`     | A question only a named person can answer is open. It names the phase waited in (`preparation` or `work`) and the person. No driver holds the item.                                                                                                                                                                                                                    |
| `prepared`    | The spec is judged ready and names the exact body revision that is the spec.                                                                                                                                                                                                                                                                                           |
| `work`        | The item is claimed for delivery. Driven by the work driver.                                                                                                                                                                                                                                                                                                           |
| `ready`       | A stamp bound to a commit exists. The integrator takes the item as a candidate at that commit. Until the integrator admits it, a work driver may hold it to test a stated reason against it (Returning a ready item to preparation).                                                                                                                                   |
| `delivered`   | The integrator recorded delivery at the confirmed final commit of the shared branch.                                                                                                                                                                                                                                                                                   |
| `design`      | The creative lane's own machine drives an undelivered item outside the task lane while its design is not complete and the item is stored in a legacy phase or stored as `preparation` with a creative episode open (Creative records and the creative capabilities). Once the design is complete the item reads as its stored phase gives, by the reading table below. |

An item in the icebox keeps its phase; the icebox is a status. The task lane stays outside this vocabulary: a todo of kind task is driven by the task procedures whatever its stored phase, including the shared `prepared` while its plan awaits authorization, and no entry verb, claim, driver, phase-changing act or holder-dependent control of this machine applies to it (the claim, the prepared, waiting, decision, stamp, kickback, release and work-cycle acts). The note act, which records context and moves nothing, and the create verb stay available for a task; a session ending still releases the claim its platform path releases.

### Acts and who may perform them

| Act                                                           | Performed by                                                    | Holder-checked                                         |
| ------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------ |
| `create`                                                      | any session with todo write                                     | no                                                     |
| `claim`                                                       | the driver session the entry verb started, on an unclaimed item | no: the claim itself is the check                      |
| `release`                                                     | the holder, or the platform when the holder's session ends      | holder, or platform                                    |
| `note`                                                        | any session with todo write; context only, moves no state       | no                                                     |
| intent-body edit                                              | the holder or a session in its claiming group                   | yes                                                    |
| `reviewed` (bound to a commit), `finding` (bound to a commit) | the work driver                                                 | yes, holder only                                       |
| `reply` (naming a finding)                                    | a session with the builder role in the holder's claiming group  | yes                                                    |
| `prepared`, `waiting`, `stamp`, `kickback`                    | the driver of the item's phase                                  | yes, holder only                                       |
| `decision` (naming the wait it answers)                       | the session of the person the item waits on                     | no: the item is unclaimed; checked against that person |
| `delivered`                                                   | the integrator under its lease, for a candidate it admitted     | no: checked against the lease and the candidate        |

On a `ready` item the driver is the work driver that holds it under the return of a ready item to preparation. That holder may perform only `kickback`, `release` and `note`; any other act is refused there, naming the phase and these three acts.

The admissible roles are the catalog roles (`local/projects/teleclaude/spec/feature/identity/agent-roles`) that the four v2 procedures declare. Role, session and act come from the authenticated session and the sealed verb, never from text an agent types. A refusal names the act and the performer it requires and changes nothing.

### The person's session

A session is a person's own session when all three hold: its principal resolves to that person's configured identity, no other session started it, and no dispatcher, job or procedure activation launched it under a role. A session with the person as principal and any other launch fact is lineage, not the person (`general/concept/lineage-vs-authorship`). A person must hold authority over the project for an item to wait on them. The identity facts are those the calling client carries; a process that drops or forges them can pass the check, and inside the person's own session a decision the person directed cannot be told from one the session's agent made on its own initiative.

### Reading an item's phase

A stored phase value from before this vocabulary is read as a phase of it, and the stored value is replaced by the normalization or conversion below at store activation, at a restore or when a deferred conversion completes, and otherwise at the item's next phase write. A stored record carries no body revision that is its spec, so it is never read as `prepared` and never starts `work`.

| Stored phase                                                                                                                                                                | Read as                                                                                                                                                                                                                                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `draft` through `plan_review`, `diagnose`, `blocked`, `prepared`, `build_started`, `build_complete`, `review_changes_requested`                                             | `preparation`; existing artifacts are the input and an existing branch and worktree are kept                                                                                                                                                             |
| `finalize_ready`                                                                                                                                                            | `ready` at the finalize handoff's commit, with the carried review approval as the stamp; `preparation` when the integration head is known and is another commit and no driver holds the item, `work` when a driver holds it                              |
| `review_approved`                                                                                                                                                           | `ready` at the carried review's commit when that commit is the integration head; `work` when a driver holds the item and the head has moved; otherwise `preparation`                                                                                     |
| `ready` with a stamp of this machine, not admitted by the integrator                                                                                                        | `ready` at the stamp's commit; when the integration head is known and is another commit, `work` for a stamp performed by a driver or a carried stamp under a Work driver's hold of the ready item, and `preparation` for a carried stamp no driver holds |
| `delivered`                                                                                                                                                                 | `delivered`                                                                                                                                                                                                                                              |
| any phase of a non-task item except `delivered`, with a recorded active admission                                                                                           | `ready` at the admitted commit until the integrator retires the admission                                                                                                                                                                                |
| any phase of a todo of kind task, including `task_plan_drafting`, `task_running` and the shared `prepared`                                                                  | unchanged: the task lane, outside this vocabulary                                                                                                                                                                                                        |
| a legacy phase, or `preparation` with a creative episode open, of a non-task item except `delivered`, without an active admission, while the creative state is not complete | `design`; once it is complete, a legacy stored phase with a deferred episode open reads `preparation` and every other stored phase is read by this table                                                                                                 |

A carried finalize handoff or review verdict is a stamp at its commit, recorded with the source it was carried from. A carried stamp that goes stale while no driver holds the item returns the record to `preparation`, as the table already does for a `review_approved` verdict that is not at the head, because no recorded revision supports `work`; under a Work driver's hold of the ready item (D14) whose head moved it reads `work`; a stamp performed by a driver of this machine, including one made in `work` entered from a carried record, has the source performed and reads `work` when stale. Only the normalization of a legacy record and a restore write a carried source; the stamp act always writes the performed source; clearing a stamp (the claim that clears a stale stamp, a held head move, a kickback) clears its source, so a stamp performed later never inherits a carried one. A performed stamp bound to a commit that is no longer the integration head is stale while the integrator has not admitted the item: the item reads as `work` again, the next entry verb for work claims it and clears the stale stamp, and the driver stamps the new head. An integration head that cannot be read leaves a stamp as it is. Once the integrator has recorded an active admission, the item reads as `ready` at the admitted commit whatever the integration head, stamp or creative state does afterwards: no driver is reserved or claimed for it, a new stamp is refused, and delivery and cleanup run under the integrator alone. The admission ends through the integrator's terminal lifecycle: delivery leaves the item `delivered`; parking retires that drain's attempt and permits the ordinary phase reading again. A candidate the integrator has queued, has in progress or has parked keeps its checkpoint and candidate key. Reading a phase never withdraws one.

While a work driver holds an unadmitted `ready` item under the return of a ready item to preparation, the item is still read as `ready` at the stamp's commit and is not a candidate. If the integration head moves to another commit meanwhile it is read as `work` under the same holder. Every `ready` reading in the table above is covered, including the readings of a carried finalize handoff or review verdict and the reading of an item whose parked admission was retired.

**Restored rows.** After the check that no live row of the same identity exists, a row restored from removal is classified and, where required, converted or normalized before any reader acts on it, on the same terms as an active row in Creative records and the creative capabilities, including its creative state and any admission. A restored legacy record whose creative state is incomplete opens its episode and reads `design`; completing that episode by files reads `preparation`, never readiness carried from its legacy value.

### Procedure headers

A v2 driver procedure declares the phases it drives (preparation, prepared and work, and `ready` before the integrator admits it; an item waiting in a phase is driven by that phase's driver), the child procedure it dispatches and each act that ends its phase with the phase that act leads to (`general/spec/snippet-authoring-schema`). Which ending acts a declaration may name, and the phase each leads to, are the machine's, not the header's: the table below is the one owner, and a header can neither widen who may perform an act nor redefine its effects (the helpers ended, the claim released, the events raised). The phase an item is held in is the phase the driver acts in, so a driven `prepared` is validated as `work`: the claim of a prepared item writes `work` in the same commit. Documentation validation refuses an ending act that is not admissible in the held phase a declaration lists it for, and a `leads_to` that differs from the act's postcondition in the table.

| Ending act | Admissible in the held phase | Leads to      |
| ---------- | ---------------------------- | ------------- |
| `prepared` | `preparation`                | `prepared`    |
| `waiting`  | `preparation`, `work`        | `waiting`     |
| `stamp`    | `work`                       | `ready`       |
| `kickback` | `work`, `ready`              | `preparation` |

`release` is the holder's control in every held phase and leaves the phase as it is; it is available whether or not a header lists it, and a scope cannot remove it. A header that does list it, as the work procedure's `ready` scope does, names the held phase as where it leads. The acts that are not ending acts (`note`, `reviewed`, `finding`, `reply`) are admitted by their own performer and phase rules in the acts table, never by an ending-acts list. The instruction a held driver receives is tied to the phase it is actually held in and to the publication it started under, including a prepared item after its claim, which is held as `work`, and a `ready` item whose head moved, which is held as `work`. A declaration may scope its child and its ending acts to one of the phases it drives, and the scope governs what is admitted, not only what is rendered: the child command starts only the child of the item's phase scope and refuses a scope that has none, and the act command admits in a phase the acts that phase's scope and the acts table allow. A published set that predates scopes reads as one with no scopes, and a driver started under it keeps parsing it. The work procedure scopes `ready` with no child and two ending acts, `kickback` leading to `preparation` and `release` leading to `ready`, and its `prepared` and `work` keep the procedure's builder and acts. `design` is driven by the creative lane's own machine, and `ready` after admission and `delivered` by the integrator; none of those carries these declarations. The machine's steps come from those declarations: a driver that starts after a published change receives the instruction the change gives, and a driver that started before keeps the declarations it started under, together with the child it dispatches. Every phase a v2 procedure drives has exactly one driving procedure; documentation validation refuses a driver without its declaration, a value outside these vocabularies, two procedures driving one phase, and a driven phase with no procedure.

### Entry verbs

The machine is called through the verbs that prepare and work an item. Called by a session that does not hold the item, a verb starts the driver of the procedure the headers name for the item's phase and returns its session, or refuses naming the one cause: held by a session; a driver start in progress; a live session of an earlier claim on the item, with the overseer as the door (Helpers of a driver); waiting on a person; admitted by the integrator at a commit; the phase and the verb that drives it; unmet dependencies; or a body revision that no longer matches. On a `ready` item the work verb takes a reason (Returning a ready item to preparation). A plain push to the branch of a work item whose driver has ended starts no driver; only a request to work the item does.

An entry verb of this lifecycle machine applied to a todo of kind task refuses naming the task lane and writes nothing, and so does a phase-changing or holder-dependent act, including release by a holder; the note act and the create verb are not refused.

A work start from `prepared` is admitted only while the intent body is at the revision the prepared act named (#124 INV-S3). The check runs in the write that reserves the start. It runs again where procedure activation judges, immediately before creating or waking the work driver, whether the start's request still stands (`local/projects/teleclaude/design/architecture/procedure-activation`). It runs a third time in the driver's claim. A mismatch, or an item or body that cannot be read, prevents the start: no work driver is created or woken, the request is not delivered, and launch recovery releases the reservation once that request can produce no driver. The item stays `prepared`, and the next work start is refused naming both revisions until preparation marks it prepared again.

The driver a verb starts claims by presenting the reservation it was started for; a claim without it, or with another, is refused. Called by the holding driver, a verb returns the instruction for the phase: the phase and claim, the child procedure to dispatch with its arguments and launch defaults when no live child exists, the acts that end the phase with the phase each leads to, and the reminders and formatting the lifecycle already carries. The commands that perform the acts, start the child and return these results are `local/projects/teleclaude/spec/feature/workflow/item-acts`.

### Returning a ready item to preparation

A `ready` item that the integrator has not admitted can be returned to preparation when a stated reason shows it wrong. This adds no act, role or authority: the work driver that holds the item before admission performs `kickback` or `release`, the holder-checked acts it performs in `work`.

- **What starts it.** An entry call that states a reason: `telec todo work <item> --reason <text>`, from a session, on an item that is unclaimed, has no driver start in progress and no active admission. The call starts a work driver for the item. A call without a reason is refused naming the reason it needs and writes nothing, so a retry or a reflex call takes nothing out of candidacy. `telec todo prepare` on a `ready` item is refused naming the work verb with a reason. The lifecycle runner requests no driver for a `ready` item. A person who finds a ready item wrong calls the verb from their own session; the driver that starts holds the claim, not the caller.
- **Every caller's reason is recorded.** Each call writes its reason as a reason note attributed to the calling session: together with the start when the call starts the driver, and on its own when the item is already held or starting. In that case the call is refused naming the holder or the start, and names its note. The same session repeating the same reason within the current stamp's cycle is a retry of the same invocation: it returns or attaches to the outcome of the earlier call, with no new note and no new driver. For a carried handoff or verdict the cycle begins at its recorded time, and a new stamp begins a new cycle. A different session, a different reason or a new cycle is new input. The machine knows which notes are reasons from the attribution the verb records, never from the text of a note.
- **The item stays ready and leaves candidacy.** From the start until the claim is released the item remains `ready` at its commit with its stamp and its ready time, and the integrator cannot admit it. The start and the admission are decided on the item itself, and exactly one takes effect. If the admission does, the entry call is refused naming the admission, and the integrator delivers or parks the item. If the start does, the admission is refused naming the holder or the start, and nothing is merged.
- **The instruction.** The driver of a held `ready` item receives the phase `ready` at its commit, the claim, every reason note and other note since the stamp (for a carried handoff or verdict, since its recorded time), and the two ending acts. It dispatches no child. The instruction carries a key, and `release` of a held `ready` item presents it. The release is refused, naming the first such reason, when a reason was noted after the instruction that key belongs to; a driver that never received an instruction has no key and cannot release, so no reason is released unseen. The platform's release at the end of the driver's session needs no key.
- **What the driver judges.** It tests the stated reasons against the prepared spec at its revision and the delta at the stamped commit. When a reason shows the spec wrong or unbuildable, or the commit not meeting the spec, it performs `kickback` with a reason of its own that says which. Otherwise it notes why the reasons do not hold and performs `release`. Either way it ends its phase in the turn in which it judges.
- **`kickback`.** One commit: the phase becomes `preparation` and the reason is a note; the stamp is cleared, as is the standing of any carried finalize handoff or review verdict as a stamp, so no later candidate scan reads the item as `ready` from them; the prepared revision no longer authorizes work; the branch and worktree are kept; every live helper of the driver is ended; the claim is released last. Interrupted at any step, the item is either still held or in `preparation`, and never unheld while still `ready` on a cleared stamp.
- **`release`**, or the end of the driver's session, leaves the item `ready` at its commit with its stamp and its original ready time. The integrator orders it by that ready time as if it had never been held.
- **The held standing is visible.** `telec todo show` and the todo projection report a held `ready` item as `ready` at its commit, held by a session since a time, with the stated reasons.
- **A head that moves while held.** If the integration head moves to another commit while the item is held, the item is read as `work` under the same holder, and a second entry call is refused naming the holder. The holder's next entry call clears the stale stamp and writes `work` as the stored phase in the same write, replacing a carried legacy value too, so a later release leaves the record in `work` and no reader rereads an old legacy value as `preparation`, and returns the instruction for `work` from the publication the holder started under, with the builder as its child. If the head returns to the stamped commit before that call, the item is read as `ready` again, held, and the stamp stands. From the clearing on, the driver is an ordinary work driver: `kickback` returns the item to preparation and `release` leaves it in `work`, unclaimed.
- **Admission is the boundary.** Before the integrator dequeues an item (scanned or queued) it is not admitted, and a start that takes effect first keeps it out of the queue's next admission. Once the item is dequeued, in progress or committed, it is admitted and is never kicked back; an entry call is refused naming the admission. A parked item is no longer admitted: parking retires the admission and the item is read by the ordinary reading, so if it reads `ready` the return applies.

### Hold

`hold` is the brake on autonomous dispatch and on admission; what sets it is unchanged. The lifecycle runner starts no driver for a held item and the integrator admits no held item. An entry verb that starts a driver on an unclaimed held item in preparation, prepared or work clears the hold in the same write as the start, with a note that names the verb and the calling session; a refused call leaves the hold as it is. Whether the start is the lifecycle runner's or an explicit call is decided inside the write that reserves the driver, from the state read there, never from an earlier snapshot: a runner start of a held item is refused, and an explicit start clears the hold. On a held `ready` item the return leaves the hold set: after `release` the item is `ready` and still held, so it is not a candidate; after `kickback` it is in preparation and still held, so the runner does not dispatch it, and the next explicit prepare start clears the hold. The hold on a `ready` item is cleared only by the brake's own release, `telec todo update <item> --release`.

### Helpers of a driver

An agent session writes the intent body only as the holder or a session in its claiming group; the artifact write surface checks that inside its own row transaction, against the holder read there, so a release or a new claim that lands while a write is deciding refuses the write. The authority is the holder's and its claiming group's and no role alone grants it: a holder or group session in `preparation`, `prepared` or `work` is not excluded for its role, a held `ready` item admits no edit, and an unclaimed item, a session with no claim and a session of an earlier claiming group have none. Direct human-identity writes without an agent session keep the permissions in `local/projects/teleclaude/spec/feature/workflow/artifact-versioning`, Write authority; input removal remains refused there.

A session starts a helper only while it still holds the item and is not releasing it; the start is recorded on the item before the session is created. Every act that releases a holder's claim (`prepared`, `waiting`, `stamp`, `kickback` and `release`) marks the claim as closing in its own commit, so a later helper start is refused, and then ends every live session started from the holder, transitively and on any computer, and waits for every recorded start to finish and end, repeating until none is live or in flight. The holder is not among them: it finishes its own act and turn and ends normally afterwards. The claim is released last, only after that sweep found nothing. When a holder's session ends without such an act the platform releases its claim and ends no session: the live sessions of that claiming group remain, belong to no holder's group, cannot perform the holder-group acts or edit the intent body, and are supplied no findings. While a live session of an earlier claiming group exists on the item, every entry call is refused naming that session and the overseer as the door, so two builders never share a worktree and the remaining session stays the overseer's to resolve. The claiming group is the holder and every session started from it, transitively and on any computer; the sweep ends the sessions started from the holder, never the holder. The earlier claims are all those the item records, including a claim recorded before this vocabulary. The same refusal applies to a driver start that the owner's decision would make: the decision records the person's answer and clears the wait, and the driver is started by the next entry call once the session has ended. Once it has ended, the next entry call drives the item from the store. A commit such a session publishes is reviewed in the next work driver's delta and makes any stamp stale; nothing is delivered on it.

### Acts only the previous machine knew

A verb that applies an act only the previous machine knew is refused at its write surface, naming the item's phase and the door for its state, and writes nothing. No stamp field the previous machine kept reaches an item this machine drives. The acts are every previous-machine stamp type (requirements, plan, PRD approval, architecture, diagnosis, drift, verdict, deferrals, build-complete, finalize-ready and kickback) and the return to work. The door is the first row of this table that matches the item's state:

| State                             | Door the refusal names                                                                                                             |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| held by a session, any phase      | the holding session; on `work` or a held `ready` item, its `kickback`                                                              |
| a driver start in progress        | the start, and the session it is starting                                                                                          |
| admitted by the integrator        | the admission at its commit; the integrator delivers or parks it, and a parked item is then reachable by the `ready` or `work` row |
| waiting on a person               | that person's decision, which starts the waited phase's driver; from `work`, that driver may kick back                             |
| `ready`, unclaimed, not admitted  | `telec todo work <item> --reason <text>`                                                                                           |
| `work`, unclaimed (a stale stamp) | `telec todo work <item>`, whose driver may kick back                                                                               |
| `prepared`, unclaimed             | `telec todo work <item>`, whose driver may kick back                                                                               |
| `preparation`, unclaimed          | none needed: the item is in preparation, which `telec todo prepare <item>` drives                                                  |
| `design`                          | the creative lane, `telec todo design <item>`; the item reaches `preparation` when its design completes                            |
| `delivered`                       | none: the item was delivered at its commit; follow-up work is a new item, `telec todo create`                                      |

Where an act of this machine replaces the retired one, the refusal also names that act with the performer the acts table gives for it: the holding driver for `prepared`, `waiting`, `stamp`, `kickback` and `finding`; the session of the waited-on person for `decision`, which answers a recorded wait and replaces no approval; any session with todo write for `create`. A retired approval that nothing replaces, such as the PRD approval, names only the door from the table.

### Creative records and the creative capabilities

**The creative episode.** The creative lane works an item inside a recorded creative episode: a record on the item, written in the same transaction as the creative entry that opens it, naming when and by which path (conversion or capability) it was opened. The episode is open until the first later claim of a driver closes it; that claim already requires the creative state to be complete, and it clears the episode in the write that makes the claim. A second creative entry after an earlier claim or a kickback opens a new episode; a creative entry while one is open returns that episode and opens none. Preparation written by `prepared`, `decision` or `kickback` alone never opens an episode, so a creative regression does not send an item back to `design` that a driver has already claimed or that was returned from work. The episode is a fact about the lane's current work; the record of which rows were converted at activation is immutable history and decides nothing about an open episode.

**What reads as `design`.** An item reads `design`, without an active admission and outside the task lane and `delivered`, while its creative state is not complete and either of these holds: it is stored in a legacy phase, or it is stored as `preparation` with a creative episode open. A record stored in a legacy phase with a deferred episode open reads `preparation` once its creative state is complete. A record stored in `waiting`, `work`, `ready` or `prepared` with a prepared record is never read as `design`, whatever its artifacts or files do afterwards. When the creative state is complete the stored phase is read by the table above, a stored `preparation` with an episode open reading `preparation`.

The legacy phases are `draft`, `prd_drafting`, `prd_review`, `prd_human_approval`, `architecture_drafting`, `architecture_review`, `diagnose`, `plan_drafting`, `plan_review`, `blocked`, `build_started`, `build_complete`, `review_changes_requested`, `review_approved` and `finalize_ready`, and `prepared` when the record carries no prepared record. A legacy record whose creative state is complete keeps the reading the table gives it.

**Conversion.** Store activation, a restore, and a creative capability each convert a record of a kind other than task that is stored in a legacy phase, has no active admission, and whose creative state is not complete: its stored phase becomes `preparation` and a creative episode is opened, in one write that changes no other recorded fact (the holder, the claim, its epoch, the ledger, the integrator's checkpoint entry and candidate key stay). The record reads `design` before and after; when its creative state completes, by any means, it reads `preparation`, with or without a holder, and never `ready` from a legacy value it carried before; the first later claim closes the episode.

**Complete legacy records are normalized forward.** Store activation, a restore and the completion of a deferred conversion also rewrite a legacy record of a kind other than task that has no active admission, has no creative episode opened for it and whose creative state is complete, into the latest shape with the reading the table above gives it unchanged: a carried `finalize_ready` handoff, and a `review_approved` verdict at the integration head, become a stored `ready` with a stamp at the handoff's or verdict's commit and ready time, the stamp recording its source as a carried handoff or a carried verdict, with its acting session empty (the carried reviewer stays legacy provenance and is not a stamping driver or initiator of this machine) and raising no ready event, since no driver of this machine stamped it; a `review_approved` verdict that is not at the head, every other legacy phase and a `prepared` without a prepared record become `preparation`. A record that a retired kickback or drift flag keeps out of candidacy mints no stamp, because a stamp would supersede that flag: it becomes `preparation`. A `review_approved` verdict whose integration head cannot be read is neither withdrawn nor given a head it does not have: activation writes nothing for it and counts it as classified, the pass that can read the head completes the normalization, and until then it reads `preparation` because its commit is not established as the head. While the head cannot be read, no driver is started for such a record held by nobody: the prepare and work verbs and the runner refuse it naming the unreadable integration head, so a preparation claim never holds an item the next pass would normalize to `ready`, and the carried verdict is neither withdrawn nor driven on a guess. A preparation claim of any record that reads `preparation` from a value the head decides stores `preparation` in its own claim write and clears the carried stamp and its source in that same write that sets the holder, with every other recorded fact unchanged. That covers a carried `finalize_ready` or `review_approved` record whose head is known (a verdict away from the head, or an integration ref found absent) and a stored `ready` whose carried stamp the head has moved past, so a holder never turns a carried stale stamp from `preparation` into `work`. The phase that was read is the phase that is held and a head that later equals the verdict cannot turn the record into a `ready` item under a preparation driver; the claim never rewrites a record while the head is unreadable, because it is refused then. This is the state of an unreadable head only: an integration ref the read found absent is a known state, and the record reads as the table gives. The retained limit is that, while the remote cannot be read, such a record cannot become a candidate and cannot be started; the scan needs the head too, and nothing is lost, since the carried verdict is unchanged. Nothing else the record carries changes: the holder, the claim, its epoch, the ledger, the checkpoint entry and candidate key stay. The record then holds a closed phase of the machine, so a later regression of its creative files never reads it as `design` and it needs no memory of one; no read, refused call, worktree or command-line reader writes anything, and no legacy stored value remains in an activated store except an actively admitted attempt, which is normalized or converted by the first pass that finds it without an active admission, and a `review_approved` verdict whose integration head cannot be read, which is classified at activation and completed by the first later pass that can read the head. Each rewritten row is recorded in the converted-row history and covered by its fence.

**Admission at activation.** An item is admitted when its row records an admitted commit. A queued or parked checkpoint entry is not an admission: such a record is converted directly, its checkpoint entry and candidate key preserved. A candidate the integrator's checkpoint names in an active, non-idle state (dequeued, in progress or committed) is admitted under the return of a ready item to preparation, but a row written before this vocabulary records no admission for it. Activation therefore keeps an admission the row already records (the admission write precedes the checkpoint's publication of it) and, only when the row records none, establishes the row's admission from the exact identity of the active checkpoint candidate (item, branch and commit; a candidate whose identity differs from a recorded admission refuses the activation), leaving the stored phase, the holder, the checkpoint entry and the candidate key unchanged, so no driver is reserved for it during integration. The checkpoint is read again inside the activation's own write transaction for this, never from a read made before it: a park writes the checkpoint before it retires the row's admission, so activation either sees the park and converts the record directly, or its admission lands before the park retires the matching commit. A delivery wins over both. If the record's creative state is not complete when activation observes it, the same write opens its creative episode as a deferred conversion, which preserves that it was incomplete when first observed. When the park later retires the admission, the deferred episode keeps the record reading `design` while incomplete and `preparation` when complete, never `ready` from its legacy value whatever its files do; a new admission is refused for it until the next pass has applied the conversion, writing `preparation` and keeping the episode when its creative state is incomplete, or, when it has since completed, persisting `preparation` and keeping the episode until the first claim of a driver; a record that has had an episode is never normalized forward to `ready`. Admission retirement preserves the exact attempt through park and checkpoint reset (`local/projects/teleclaude/spec/feature/workflow/integration-state-machine`). While a deferred episode is open the record is not a candidate: the candidate scan skips it and the admission write refuses it. When the checkpoint cannot be read, the store is not activated and no record in it is converted, and the refusal names the recovery that exists for the checkpoint, `telec todo integrate`; the integrator's entry, including its reading of delivered items and its reset of an idle checkpoint, is outside the refusal for an unmarked store, so that door runs before any scan.

**The creative capabilities** (the design-spec write, the creative gate stamps and `telec todo design`) act on an object state decided inside the capability's own row transaction, on the state read there. Where a refusal names a door, it is the door of the first matching row of the table in Acts only the previous machine knew.

| #   | Object state                                                                                                                                                                                                                                                    | Creative write, stamp or dispatch                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | kind `task`, or stored `task_plan_drafting` / `task_running`                                                                                                                                                                                                    | unchanged by this contract                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| 2   | stored `delivered`, or a delivered or removed row                                                                                                                                                                                                               | refused; the item is done                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 3   | admitted (the workflow record's admitted commit, which activation establishes from an active checkpoint candidate); a recorded admission is known without the checkpoint, and a row that records none while the checkpoint is unreadable is unknown and refuses | refused; the integrator's delivery or park retires the admission                                                                                                                                                                                                                                                                                                                                                                                                      |
| 4   | a closed phase of the machine: `waiting`, `work`, `ready` not admitted, or `prepared` with a prepared record, held or not                                                                                                                                       | refused; the phase and its claim are never moved by a creative write                                                                                                                                                                                                                                                                                                                                                                                                  |
| 5   | held by a session other than the caller, any stored phase                                                                                                                                                                                                       | refused                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 6   | held by the caller, stored as `preparation`                                                                                                                                                                                                                     | only `telec todo design` by the holder: one commit opens the episode, converts a legacy phase if there is one, records the creative dispatch as a durable intent and marks the claim closing; the sweep of the holder's helpers then runs as for any releasing act, the dispatch completes idempotently only after the sweep found nothing, and the claim is released last (Helpers of a driver); the design-spec write and the gate stamps by the holder are refused |
| 7   | unheld, stored in a legacy phase                                                                                                                                                                                                                                | allowed; the capability converts the record and opens the episode in its own transaction, with its artifact or stamp                                                                                                                                                                                                                                                                                                                                                  |
| 8   | unheld, stored as `preparation`                                                                                                                                                                                                                                 | allowed; the capability opens the episode in its own transaction, with its artifact or stamp, unless one is open                                                                                                                                                                                                                                                                                                                                                      |

The artifact or the stamp, or the durable intent to dispatch, commits together with the episode it opens; a refused call writes neither. The dispatch itself is an effect the machine completes idempotently after that commit, not part of it. A call that fails before its commit, because the record cannot be written, the claim changed while it was deciding, or the checkpoint cannot be read, is refused naming that cause and wrote nothing, so the same call repeated once the cause has gone is a fresh call. A call whose commit landed and whose response was lost is a retry: it returns the same committed episode and outcome and completes any effect still pending. The result names the episode.

### Notes

Notes are appended to the item's log by the sealed act command and read as prose a person can follow. The machine reads acts from the attribution the verbs record and never from note text; log text that looks like an act but was not written by a verb is no act.

### Use cases

#### UC-IL1: The machine follows the headers

```gherkin
Given a published change to a driver procedure's declarations, such as the child's thinking mode or the phase an act leads to
When a driver that started after the publication calls its entry verb
Then the instruction it receives reflects the change and no code changed
And a driver that started before the publication receives the instruction its own declarations give
```

#### UC-IL2: Claim for preparation

```gherkin
Given an unclaimed item in preparation whose dependencies are complete
When any surface that starts preparation is used
Then exactly one driver session holds the claim
And that session's title is its catalog role followed by its arguments
And a claim note names the session
```

#### UC-IL3: The spec is authored and challenged

```gherkin
Given the preparation driver holds the claim
When it dispatches the author the instruction names
Then the author edits the item's intent body and appends notes
And every note carries the role, session and act of the session that wrote it
```

#### UC-IL4: Prepared names the judged revision

```gherkin
Given the preparation driver judged the intent body at revision R
When it performs the prepared act naming R
Then the item is prepared naming R and the claim is released
But if the intent body is no longer at R the act is refused naming both revisions and nothing is written
```

#### UC-IL5: Waiting on a person

```gherkin
Given the driver states a question that a person with authority over the project owns
When it performs the waiting act naming that person and the question
Then the item is waiting, naming the phase waited in and the person
And the claim is released and the driver ends
And any surface that starts a driver refuses, naming the person
But naming a person with no authority over the project is refused
```

#### UC-IL6: The owner's decision resumes the phase

```gherkin
Given an item waiting on a person
When that person's own session performs the decision act with their answer, naming the wait it answers
Then the answer is in the log as theirs and the waiting clears
And the driver of the waited phase starts exactly once and reads the answer as the person's input
But the decision act from any other session, including one dispatched from the person's session, is refused and clears nothing
And a decision naming a wait that is not the open one is refused and clears nothing
And a note from that session stays in the log and the next driver reads it as context
```

#### UC-IL7: Claim for work

```gherkin
Given a prepared item naming revision R whose dependencies are complete
When a surface starts work
Then the claim moves to one work driver session and the item is in work
And a claim note names the session and the branch, whose names derive from the item identity
But if the intent body is no longer at R work is refused naming both revisions and the item is unchanged
And if the intent body leaves R, or cannot be read, after the start is reserved and before the work driver is created or woken, no work driver is created or woken and the item stays prepared
```

#### UC-IL8: Kickback

```gherkin
Given the work driver holds the claim
When it performs the kickback act with a reason
Then the item is in preparation and the reason is a note
And the prepared revision no longer authorizes work
And the branch and worktree are kept, the builder is ended and the claim is released
```

#### UC-IL9: Racing starts leave one holder

```gherkin
Given two surfaces start preparation of the same unclaimed item at once
When both complete
Then exactly one driver holds the claim
And the loser writes no note and causes no claim change
```

#### UC-IL10: An act from the wrong performer is refused

```gherkin
Given an act that the table above allows only the item's holder or only a builder in its claiming group
When any other session performs it
Then it is refused naming the act and the performer it requires
And nothing is written
```

#### UC-IL11: An item recorded before this vocabulary is read in it

```gherkin
Given a stored item at a phase from before this vocabulary
When any surface or the machine reads it
Then it is read at the phase the reading table gives and that phase's driver drives it
```

#### UC-IL12: An act only the previous machine knew is refused

```gherkin
Given an item driven by this machine
When a verb applies an approval, return or handoff act that only the previous machine knew
Then it is refused naming the item's phase and the door for its state
And no phase moves and nothing is written
```

#### UC-IL13: A live holder from before this vocabulary keeps its claim until it ends

```gherkin
Given a session from before this vocabulary holds a claim on an item
When it calls the previous machine, or a surface starts a driver for that item
Then the call is refused with an instruction to end the session, and the surface names the holding session
And when that session ends its claim is released and the next surface call drives the item from the phase the reading table gives
```

#### UC-IL14: A task stays on the task lane

```gherkin
Given a todo of kind task whose plan awaits authorization and whose stored phase is prepared
When an entry request to the v2 lifecycle machine, or a phase-changing or holder-dependent act (claim, prepared, waiting, decision, stamp, kickback, release), is applied to it
Then it is refused naming the task lane and nothing is written
And the task procedures and their authorization continue to drive it, unchanged
And a note on the task is still recorded
And the release of its claim by the platform when its session ends is unchanged
And a running task firing is not released by an act, so no second firing starts beside it
```

#### UC-IL15: A ready item that is wrong goes back to preparation

```gherkin
Given a ready item the integrator has not admitted
When a person's session asks for it to be worked on again and states why
Then the item stays ready and is not a candidate while a work driver tests the reason against the item's spec and commit
And when the driver finds the reason sound the item is in preparation with the reasons recorded, its branch and worktree kept, and it is not admitted on the stamp it carried
But the same request without a reason is refused naming the reason it needs and the item remains a candidate
And when the driver finds the reason does not hold, the item stays ready at its original time and is delivered in that order
```

## Known caveats

- A work driver that holds a `ready` item delays its delivery for as long as it holds it. No time bounds the held standing: a claim lives as long as its session, and a driver that stays alive without ending its phase keeps the item out of candidacy until its session ends or the claim is released by hand. The exposure is a delay, never a delivery of something wrong, and `telec todo show` reports the holder, since when and the stated reasons.
- A driver whose session ends without ending the sessions it started leaves them running, because the platform ends no session. The item then waits for the overseer, which a person invokes, and the entry refusal and `telec todo show` name the running session.
- A person's session is identified by facts the calling client carries; the platform does not establish them from infrastructure-owned state.
- An item whose driver ends without the platform learning of it keeps its claim until it is released by hand.

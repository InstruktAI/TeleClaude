---
description: How a builder's published commits wake the work driver, how the driver's findings reach the builder, and how a stamp bound to a commit makes an item ready for the integrator.
delivered_by: [issue-128]
---

# Work Review Cycle — Spec

## What it is

In work, two agent sessions cooperate on one item: the work driver, which holds the claim and scrutinizes every commit, and the builder, which owns the code. This spec owns what connects them on the item's own record: the notice that a commit reached the integration head, the findings the driver places against commits, and the stamp that makes the item a candidate. The phases and acts are `local/projects/teleclaude/spec/feature/workflow/item-lifecycle`; the mechanism is `local/projects/teleclaude/design/architecture/workflow-machine`.

Facing: all actors are agent sessions. The integrator's guarantees (singleton lease, FIFO by ready time, resumable checkpoints, both already-integrated guards, exclusive push of the shared branch, residual-marker gate, one recorded delivery) are `local/projects/teleclaude/spec/feature/workflow/integration-state-machine` and hold as stated there.

## Canonical fields

### The integration head

The integration head is the ref of the work branch that the integrator takes. A commit that exists only locally is not a head advance. Every statement here that names the head means this ref.

### Publishing a commit

The sealed commit of a todo worktree publishes the commit it just created by that commit's identity, never by a symbolic head, as one compare-and-swap update of the integration ref. The update is leased on the tip of the ref that this clone last observed, and it is made only when the commit contains that tip or the branch's own history here once carried it, which admits a commit that was rebased. A clone that never observed the ref requires that it does not exist. When origin carries work this clone has not incorporated, nothing is published, and the committing session is told to fetch and integrate and commit again. No remote read precedes the push.

Publication never fails the commit. Around the push the sealed commit reports to the platform, as the session that is committing: the intent to push that commit from that tip, and then the push's own result. Only the holder of the item and a builder in the holder's claiming group may report. A report that cannot be delivered leaves the commit and its push as they are; the platform's own reading below covers the notice.

### Observing a head

One notice is raised for each new integration-head commit, naming the item, branch and commit. It reaches the item's work driver through the platform's event-to-session delivery for procedures. It is raised from two observation points and names only a commit that was observed on the integration ref, never one inferred from a later state of it:

- a successful publish by the sealed commit of a todo worktree, for the exact commit it published: the intent was reported, the compare-and-swap succeeded, and the completion says so. A failed publish raises nothing, and a later push that moves the ref past the published commit does not void the observation;
- the platform's own reading of each work item's integration head, at daemon start, on every tick of the platform's schedule clock, and at each machine call on that item once the call is admitted (a call that is refused observes and writes nothing). It catches a push made outside the sealed commit and a publish whose notice a crash prevented. The commit it names is the one the ref carries when it reads. The tick is the cadence at which a reading pass starts; it is not by itself a bound on when an observation succeeds. The bound is the pass's own budget. A pass first reads the computer's project inventory (within 10 seconds). For each project it then lists the items and reads their stored phase locally (within 10 seconds), and reads the remote only for the n items that are in work. Those reads run eight at a time, each within 20 seconds (its read of the remote within 10 of them) and including the sending of that item's own head notice; a read that fails or runs out of its time holds its place for its full limit and observes nothing. A project's pass therefore takes at most 10 + ceil(n / 8) × 20 seconds, the projects are passed one after another, and a whole pass takes at most D = 10 + the sum of those over all projects. The passes run in a consumer of their own, apart from the reconciliation of pending effects and the release of launch reservations, and the head notice is sent apart from the item's other pending effects, so nothing but this inventory, this setup and these reads counts toward D. The clock ticks once a minute, each tick starts a pass that reads the current ref, and passes are handled one after another. A push made outside the sealed commit is observed by the first pass that starts after it and reads it successfully: at the latest after one tick (60 seconds), the rest of the pass that was already in progress, and that next pass, which is at most max(60, D) + D seconds in all. Ticks that queue while a pass overruns add no latency of their own beyond that. A reading that fails or runs out of its time is logged and attempted again at the next pass, and counts toward nothing: it is not an observation. A head notice that was recorded but not sent is sent again by the next pass.

A publish whose outcome was not recorded, because the committing session ended between pushing and recording it, raises no notice of its own: a later head does not prove that the commit was ever the ref's tip. The current-head reading and the driver's review of the whole delta cover it.

Delivery is at least once. Heads that landed while the platform was down, or whose publish outcome was not recorded, get no notice of their own; the driver reviews everything since the last commit it recorded as reviewed, so no commit between is skipped. The driver acts once per commit: a repeated notice for a commit it already recorded as reviewed adds nothing.

### Findings

A finding is bound to the item and to a commit, not to a builder session. It is unanswered while no `reply` names it. Findings are supplied to the builder at the start of its turn and when it stops. A finding supplied at a stop and still unanswered does not hold a later stop, and is supplied again at the next turn start. A replacement builder receives the findings placed against its predecessor's commits, and a reply by an earlier builder still answers.

Only the builder session inside the holder's claiming group is supplied. At a stop, the findings are carried in the same continuation as any other reason the stop already has, so one stop emits one response, and a finding is recorded as offered only after that response was written. Supplying fails open: an unreadable item or store never blocks a turn or a stop.

The findings are item data written by the work driver, not instructions of the platform. The text the builder receives separates the platform's own instruction, which names the reply act, from the findings, which arrive encoded with each finding's key, its commit and its text, preceded by a statement that they are unvalidated item data. Text inside a finding cannot close that boundary or pass for platform text.

### Stamp

The stamp is bound to a commit H. It is accepted only from the work driver, only when H is the integration head, the item's worktree branch head is H and its worktree is clean, and only when the build gates pass at H: the worktree carries commits beyond the shared branch that change files, and the project's native test target passes. Those references are checked again after the gates ran. A refusal names the disagreeing refs or the failing gate. When the integration ref cannot be read, the refusal says so; it never reads that as the ref being absent. A stamp makes the item `ready` at H, ends the builder and releases the claim. A stamp interrupted partway and run again completes the remaining steps and never writes a second stamp or notice for H.

The stamp is submitted as a receipt-backed operation: the caller receives a receipt at once and the outcome is delivered to the calling session. The same request submitted again attaches to the same operation. At most one stamp's gates run on an item at a time: while one runs, a stamp that asks for something else is refused, and refusing it does not displace the running one. The phase and the holder are checked where the slot is taken, and a result is recorded only by the invocation that still owns the slot.

The build gates run in a detached runner process that the stamp owns through the platform's spawn registry (`local/projects/teleclaude/design/process-lifecycle`, gate runner ownership). The runner starts no test workload until the daemon has durably recorded the runner's identity, enforces the gates' time limit and ends every other process of its group before it reports, so the limit holds when the daemon ends. While the runner or any non-zombie member of its group may still run, the item's stamp slot is held: a second stamp is refused, nothing is replaced, and no process is signalled on a group number alone. A unit whose ownership cannot be shown is unknown, and the governing agent investigates it with the capabilities it already has and ends only processes it positively attributes to the gate; no act clears it.

Candidate selection takes an item only in `ready`, with a stamp bound to the current integration head. When the head moves past the stamped commit before the integrator admits it, the item reads as work again: it is not a candidate and a stamp at the new head is required. The next entry verb for work claims it, clears the stale stamp, and the driver stamps the new head. A head that cannot be read leaves a stamp as it is. Once the integrator has recorded an active admission at H, the item reads as ready at H until the integrator retires the admission; later commits, a later stamp and the creative state do not reopen it and are not part of that delivery. Delivery leaves the item delivered; parking retires the attempt for that drain and permits the ordinary phase reading again.

The integrator admits every `ready` item whose stamp is at the integration head whether or not a notice for it was ever raised or consumed. Candidates are ordered by ready time; an item read as `ready` from before this vocabulary uses the ready time its carried handoff or review recorded.

### Use cases

#### UC-RC1: A published commit reaches the work driver

```gherkin
Given the builder publishes a commit that becomes the item's integration head
When the platform observes that head
Then exactly one notice names the item, branch and commit
And the session holding the work claim receives it whatever the builder writes in its turn
And the driver reviews everything since the last commit it recorded as reviewed
```

#### UC-RC2: Only a confirmed head raises a notice

```gherkin
Given a builder whose publish failed, or whose commit exists only locally
When the platform reads the item's integration head
Then no notice names that commit
But a commit pushed by plain git is observed by the platform's periodic reading and raises its notice
```

#### UC-RC3: A repeated notice adds nothing

```gherkin
Given the driver recorded a commit as reviewed
When a notice for that commit arrives again, including after a restart
Then no new note or review is recorded
```

#### UC-RC4: Findings reach the builder without it looking

```gherkin
Given unanswered findings on the item
When the builder's turn starts, or the builder stops
Then those findings are supplied to it
And a finding already supplied at a stop and still unanswered does not hold a later stop, and is supplied again at the next turn start
And a finding placed while the builder is stopping is supplied no later than its next turn start
And findings supplied at a stop that already has another reason arrive in the same response as that reason
```

#### UC-RC5: A stamp makes the item ready

```gherkin
Given the item's integration head is H, its worktree branch head is H and its worktree is clean
When the work driver performs the stamp act at H
Then the build gates run at H
And a stamp bound to H exists, the item is ready at H, the builder is ended and the claim is released
And the integrator takes the item as a candidate at H
```

#### UC-RC6: A stamp is refused when the refs disagree

```gherkin
Given a stamp requested by the builder, at a commit that is not the integration head, with a worktree branch head that differs from it, or with an unclean worktree
When the stamp is performed
Then it is refused naming the disagreeing refs and nothing is written
But a failing build gate refuses the stamp naming the gate
```

#### UC-RC7: A stale stamp is not ready

```gherkin
Given a stamp bound to H that the integrator has not admitted
When the integration head moves to H′
Then the item is reported as not ready and is not a candidate
And a stamp at H′ is required
And the next entry verb for work claims the item and the driver stamps H′
```

#### UC-RC8: Admission freezes the delivery

```gherkin
Given the integrator admitted the candidate at H
When the branch later advances to H′
Then the item is delivered at H and the commits past H are not part of that delivery
And while the admission is active the item reads as ready at H, no driver is reserved or claimed for it, and a new stamp is refused
```

#### UC-RC8b: A push after admission does not reopen the item

```gherkin
Given the integrator has recorded an active admission for the candidate at H
And the branch then advances to H′
When an entry verb for work or a new stamp at H′ is attempted
Then it is refused because the item is ready at H
And the delivery completes at H under the integrator
```

#### UC-RC9: A ready item is admitted without its notice

```gherkin
Given an item that is ready at the integration head and whose ready notice was never raised or consumed
When the integrator's periodic candidate scan runs
Then the item is admitted as a candidate
```

#### UC-RC10: A publish never overwrites work the clone has not seen

```gherkin
Given origin carries a commit on the item's branch that the builder's clone has not incorporated
When the builder commits
Then the commit is recorded locally, nothing is published, and the builder is told to fetch and integrate
And a commit that was rebased from a branch that once carried the observed tip is published
```

#### UC-RC11: A second stamp does not run beside the first

```gherkin
Given a stamp whose build gates are running
When another stamp asks for the same item with different content, or the first stamp's caller stopped waiting and repeats it
Then the different stamp is refused and the running one is not displaced
And the repeated request attaches to the running operation
And the gates run once
```

#### UC-RC12: Gates that may still be running hold the slot

```gherkin
Given a stamp whose runner or daemon ended while its test workload may still be running
When another stamp is requested for the item
Then the slot is not replaced while the old unit's processes may still run
And no process is signalled whose identity the platform has not positively attributed to the gate
And the refusal names the group and what remains in it
```

## Known caveats

- A commit that landed while the platform was down is covered by the driver's review of the whole delta, not by a notice of its own.
- The completion a committing session reports for its publish is a client assertion inside the sealed wrapper's local trust contract; a session that bypasses the wrapper can state a swap that did not happen. The current-head reading and the driver's review bound its effect to a wrong or missing notice, never to a wrong delivery.
- A publish assumes origin's push and fetch address the same repository, which Git itself requires; divergent push addresses are outside what this reporting can attribute.
- A head that cannot be read, because the remote is unreachable or unauthenticated, yields no notice for that item until a later read succeeds; the failure is logged with the item and project.
- A stamp's gate unit whose ownership cannot be shown holds the item's stamp until its processes end or the governing agent has ended the ones it can attribute. A process that starts a session of its own leaves the unit and is not seen by the machine, and a group that remains after its runner with no positively identified member cannot be told from an unrelated group that reused its number, so it is never signalled.

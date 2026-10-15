---
description: How a builder's published commits wake the work driver, how the driver's findings reach the builder, and how a stamp bound to a commit makes an item ready for the integrator.
delivered_by:
  - issue-128
---

# Work Review Cycle — Spec

## What it is

In work, two agent sessions cooperate on one item: the work driver, which holds the claim and scrutinizes every commit, and the builder, which owns the code. This spec owns what connects them on the item's own record: the notice that a commit reached the integration head, the findings the driver places against commits, and the stamp that makes the item a candidate. The phases and acts are `local/projects/teleclaude/spec/feature/workflow/item-lifecycle`; the mechanism is `local/projects/teleclaude/design/architecture/workflow-machine`.

Facing: all actors are agent sessions. The integrator's guarantees (singleton lease, FIFO by ready time, resumable checkpoints, both already-integrated guards, exclusive push of the shared branch, residual-marker gate, one recorded delivery) are `local/projects/teleclaude/spec/feature/workflow/integration-state-machine` and hold as stated there.

## Canonical fields

### The integration head

The integration head is the ref of the work branch that the integrator takes. A commit that exists only locally is not a head advance. Every statement here that names the head means this ref.

### Observing a head

One notice is raised for each new integration-head commit, naming the item, branch and commit. It reaches the item's work driver through the platform's event-to-session delivery for procedures. It is raised from two observation points and names only a commit that was observed on the integration ref, never one inferred from a later state of it:

- a successful publish by the sealed commit of a todo worktree, for the exact commit it published as one compare-and-swap update of the integration ref from the tip it read to that commit; a failed publish raises nothing, and a later push that moves the ref past the published commit does not void the observation;
- the platform's own reading of each work item's integration head at start, at every machine call and on every tick of the platform's schedule clock, which catches a push made outside the sealed commit and a publish whose notice a crash prevented. The commit it names is the one the ref carries when it reads. A push made outside the sealed commit is therefore observed within one tick interval of it, and the interval is the cadence the clock's event declaration owns.

A publish whose outcome was not recorded, because the committing session ended between pushing and recording it, raises no notice of its own: a later head does not prove that the commit was ever the ref's tip. The current-head reading and the driver's review of the whole delta cover it.

Delivery is at least once. Heads that landed while the platform was down, or whose publish outcome was not recorded, get no notice of their own; the driver reviews everything since the last commit it recorded as reviewed, so no commit between is skipped. The driver acts once per commit: a repeated notice for a commit it already recorded as reviewed adds nothing.

### Findings

A finding is bound to the item and to a commit, not to a builder session. It is unanswered while no `reply` names it. Findings are supplied to the builder at the start of its turn and when it stops. A finding supplied at a stop and still unanswered does not hold a later stop, and is supplied again at the next turn start. A replacement builder receives the findings placed against its predecessor's commits, and a reply by an earlier builder still answers.

### Stamp

The stamp is bound to a commit H. It is accepted only from the work driver, only when H is the integration head, the item's worktree branch head is H and its worktree is clean, and only when the build gates pass at H: the worktree carries commits beyond the shared branch that change files, and the project's native test target passes. Those references are checked again after the gates ran. A refusal names the disagreeing refs or the failing gate. A stamp makes the item `ready` at H, ends the builder and releases the claim. A stamp interrupted partway and run again completes the remaining steps and never writes a second stamp or notice for H. The gates run once per stamp invocation: a caller that stops waiting leaves the invocation running, and running the stamp again attaches to it.

Candidate selection takes an item only in `ready`, with a stamp bound to the current integration head. When the head moves past the stamped commit before the integrator admits it, the item is not a candidate and a stamp at the new head is required. Once the integrator admitted H, later commits are not part of that delivery.

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
```

#### UC-RC8: Admission freezes the delivery

```gherkin
Given the integrator admitted the candidate at H
When the branch later advances to H′
Then the item is delivered at H and the commits past H are not part of that delivery
```

#### UC-RC9: A ready item is admitted without its notice

```gherkin
Given an item that is ready at the integration head and whose ready notice was never raised or consumed
When the integrator's periodic candidate scan runs
Then the item is admitted as a candidate
```

## Known caveats

- A commit that landed while the platform was down is covered by the driver's review of the whole delta, not by a notice of its own.

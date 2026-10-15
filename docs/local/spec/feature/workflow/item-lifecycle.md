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

| Phase         | Meaning                                                                                                                                             |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `preparation` | The item's spec is being written and challenged. Driven by the preparation driver.                                                                  |
| `waiting`     | A question only a named person can answer is open. It names the phase waited in (`preparation` or `work`) and the person. No driver holds the item. |
| `prepared`    | The spec is judged ready and names the exact body revision that is the spec.                                                                        |
| `work`        | The item is claimed for delivery. Driven by the work driver.                                                                                        |
| `ready`       | A stamp bound to a commit exists. The integrator takes the item as a candidate at that commit.                                                      |
| `delivered`   | The integrator recorded delivery at the confirmed final commit of the shared branch.                                                                |
| `design`      | The creative lane's own machine drives the item. It reads as `preparation` once its design is complete.                                             |

An item in the icebox keeps its phase; the icebox is a status. The task lane's phases stay outside this vocabulary and are driven by the task procedures.

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

The admissible roles are the catalog roles (`local/projects/teleclaude/spec/feature/identity/agent-roles`) that the four v2 procedures declare. Role, session and act come from the authenticated session and the sealed verb, never from text an agent types. A refusal names the act and the performer it requires and changes nothing.

### The person's session

A session is a person's own session when all three hold: its principal resolves to that person's configured identity, no other session started it, and no dispatcher, job or procedure activation launched it under a role. A session with the person as principal and any other launch fact is lineage, not the person (`general/concept/lineage-vs-authorship`). A person must hold authority over the project for an item to wait on them. The identity facts are those the calling client carries; a process that drops or forges them can pass the check, and inside the person's own session a decision the person directed cannot be told from one the session's agent made on its own initiative.

### Reading an item's phase

A stored phase value from before this vocabulary is read as a phase of it, and the stored value is replaced at the item's next phase write. A stored record carries no body revision that is its spec, so it is never read as `prepared` and never starts `work`.

| Stored phase                                                                                                                    | Read as                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `draft` through `plan_review`, `diagnose`, `blocked`, `prepared`, `build_started`, `build_complete`, `review_changes_requested` | `preparation`; existing artifacts are the input and an existing branch and worktree are kept             |
| `finalize_ready`                                                                                                                | `ready` at the finalize handoff's commit, with the carried review approval as the stamp                  |
| `review_approved`                                                                                                               | `ready` at the carried review's commit when that commit is the integration head; otherwise `preparation` |
| `ready` with a stamp of this machine                                                                                            | `ready` at the stamp's commit; `work` when the integration head is known and is another commit           |
| `delivered`                                                                                                                     | `delivered`                                                                                              |
| `task_plan_drafting`, `task_running`                                                                                            | unchanged                                                                                                |
| any phase, while the creative state is not complete                                                                             | `design`                                                                                                 |

A stamp bound to a commit that is no longer the integration head is stale: the item reads as `work` again, the next entry verb for work claims it and clears the stale stamp, and the driver stamps the new head. An integration head that cannot be read leaves a stamp as it is. A candidate the integrator has queued, has in progress or has parked keeps its checkpoint and candidate key. Reading a phase never withdraws one.

### Procedure headers

A v2 driver procedure declares the phases it drives (preparation, prepared and work; an item waiting in a phase is driven by that phase's driver), the child procedure it dispatches and each act that ends its phase with the phase that act leads to (`general/spec/snippet-authoring-schema`). The machine's steps come from those declarations: a driver that starts after a published change receives the instruction the change gives, and a driver that started before keeps the declarations it started under, together with the child it dispatches. Every phase a v2 procedure drives has exactly one driving procedure; documentation validation refuses a driver without its declaration, a value outside these vocabularies, two procedures driving one phase, and a driven phase with no procedure.

### Entry verbs

The machine is called through the verbs that prepare and work an item. Called by a session that does not hold the item, a verb starts the driver of the procedure the headers name for the item's phase and returns its session, or refuses naming the cause: held by a session, waiting on a person, the phase and the verb that drives it, unmet dependencies, or a body revision that no longer matches. The driver a verb starts claims by presenting the reservation it was started for; a claim without it, or with another, is refused. Called by the holding driver, a verb returns the instruction for the phase: the phase and claim, the child procedure to dispatch with its arguments and launch defaults when no live child exists, the acts that end the phase with the phase each leads to, and the reminders and formatting the lifecycle already carries. The commands that perform the acts, start the child and return these results are `local/projects/teleclaude/spec/feature/workflow/item-acts`.

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
And that session's title is its role followed by the item it works on
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
Then it is refused naming the item's phase and the act that replaces it
And no phase moves
```

#### UC-IL13: A live holder from before this vocabulary keeps its claim until it ends

```gherkin
Given a session from before this vocabulary holds a claim on an item
When it calls the previous machine, or a surface starts a driver for that item
Then the call is refused with an instruction to end the session, and the surface names the holding session
And when that session ends its claim is released and the next surface call drives the item from the phase the reading table gives
```

## Known caveats

- A person's session is identified by facts the calling client carries; the platform does not establish them from infrastructure-owned state.
- An item whose driver ends without the platform learning of it keeps its claim until it is released by hand.

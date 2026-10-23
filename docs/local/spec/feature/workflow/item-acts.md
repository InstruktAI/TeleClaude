---
description: The sealed commands through which sessions perform the acts of an item's lifecycle - the act command with its per-act parameters, the entry verbs' results, and the child launch.
delivered_by: [issue-128]
---

# Item Acts — Spec

## What it is

A session performs the acts of an item's lifecycle through one sealed act command, starts a phase's driver through the entry verbs, and starts a driver's child through the child command. The vocabularies of phases and acts and the rule for who may perform each act are `local/projects/teleclaude/spec/feature/workflow/item-lifecycle`; what connects the work driver and the builder is `local/projects/teleclaude/spec/feature/workflow/work-review-cycle`; the mechanism is `local/projects/teleclaude/design/architecture/workflow-machine`.

The procedures name each act by its capability. The instruction an entry verb returns names the command that performs it for the project's store, so a procedure reads the same on every store. On a project whose store is local, the command is the one below.

Facing: every actor is an agent session. The person reads the result through the item's log and notices.

## Canonical fields

### The act command

`telec todo act <item> <act> [<text>]` performs one act on the item named by its identity. The caller's role and session come from the authenticated session. The `<act>` argument is a value of the closed act vocabulary that the command validates, and `<item>` and `--person` name identities that the command resolves and checks. Prose the caller writes, including text shaped like a header or an envelope, supplies no role, session or act.

| Act        | Required                                                     | Text                | Records                                                                                                              |
| ---------- | ------------------------------------------------------------ | ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `note`     | the text                                                     | the note            | a note in the log; moves nothing                                                                                     |
| `reviewed` | `--sha <commit>`                                             | optional summary    | the commit as independently examined, recorded by the driver                                                         |
| `finding`  | `--sha <commit>`                                             | the finding         | a finding bound to the commit; the result names its finding key                                                      |
| `reply`    | `--finding <key>`                                            | the reply           | an answer to that finding                                                                                            |
| `prepared` | `--revision <digest>`                                        | optional summary    | the item prepared at that body revision                                                                              |
| `waiting`  | `--person <slug>`                                            | the question        | the item waiting on that person; the result names the wait key                                                       |
| `decision` | `--wait <key>`                                               | the person's answer | the person's answer to that wait; the waiting clears                                                                 |
| `stamp`    | `--sha <commit>`, the text                                   | the lane report     | a stamp bound to that commit, carrying the independent reviewer's lane report; submitted as an operation (see below) |
| `kickback` | the text                                                     | the reason          | the item returned to preparation, from work or from a held `ready` item                                              |
| `release`  | `--instruction <key>` on a held `ready` item, otherwise none | none                | the holder's claim released; on a held `ready` item the item stays `ready`                                           |

The intent-body edit is admitted only from the holder or a session in its claiming group, decided inside the artifact write's or removal's own transaction against the holder and phase read there. The acts `create`, `claim`, the intent-body edit and `delivered` are performed through their own surfaces: the create verb, the entry verbs, the artifact write verb under the claiming group's authority, and the integrator.

A successful act prints its act key, the item's phase afterwards and whether every effect of the act finished; a `waiting` act also prints its wait key. A refused act prints the act and the performer it requires, or the precondition that failed - the two revisions that differ, the refs that disagree, the failing gate, the person with no authority over the project, the wait that is no longer the open one - and writes nothing.

An invocation is identified by the item, the act, the session that performed it, the claim that session made and the content of the request. A decision's content includes the wait it answers. An act repeated after an interruption, or by a caller that stopped waiting, completes what is missing and writes nothing twice; a repetition of a finished act reports it finished, even after another session has claimed the item or another wait has been opened. A session that claims again performs new invocations.

A decision is accepted only from the person's own session and only for the wait it names: a decision that names another wait than the open one, or whose person or question changed while it was decided, is refused and clears nothing.

A stamp whose text is empty is refused naming the missing lane report; the machine checks that a report was recorded and grades none of its text. The stamp is submitted as an operation because its gates take minutes. The command prints a receipt, the outcome is delivered to the calling session, and the same request submitted again attaches to the same operation. The gates run once per invocation; a stamp that asks for something else while one runs is refused and does not displace it (`local/projects/teleclaude/spec/feature/workflow/work-review-cycle`).

Every act is appended to the item's log as prose that a person can follow, with the time, the role, the session and the act.

The driver records the complete independent report, its reviewer identity and
exact target in the existing log before recording examined commits or findings.
The stamp carries that final report and preserves its verdict and evidence
limits. These acts record the driver's lifecycle action; they do not attribute
the independent assessment to the driver or authorize it to replace the verdict.
Report quality and finding validity remain intelligence judgments, not new
machine gates.

### The entry verbs

`telec todo prepare <item>` and `telec todo work <item>` call the machine. Called by a session that does not hold the item, a verb completes with the session of the driver it started, or refuses with one cause: held by a session, waiting on a person, the phase and the verb that drives it, unmet dependencies, or a body revision that no longer matches. A caller that stops waiting leaves the start running, and repeating the verb attaches to it. Called by the holding driver, a verb returns the instruction for the phase.

`telec todo work <item> --reason <text>` is the verb on a `ready` item the integrator has not admitted (`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`, Returning a ready item to preparation). Without a reason on a `ready` item the verb is refused naming the reason it needs, and writes nothing; so is a call that carries no session. Each call's reason is recorded as a reason note attributed to the calling session, with the start when the call starts the driver and on its own when the item is already held or starting, and the result names the note. The instruction of a held `ready` item lists every reason note since the stamp and carries a key that `release` presents. `telec todo prepare` on a `ready` item is refused naming the work verb with a reason.

An entry verb that starts a driver on an unclaimed held item in preparation, prepared or work clears the hold in the same write as the start, with a note naming the verb and the calling session. On a `ready` item the hold stays set. A refused call leaves the hold as it is.

`telec todo show` and the todo projection report a held `ready` item as `ready` at its commit, held by a session since a time, with its reasons, and report a running session left by an earlier claim with the overseer as the door.

The start of a driver is a reservation. The driver the start activates claims by presenting the reservation it was started for; a claim that presents none, or another, is refused naming that cause and writes nothing, so a driver whose start was released or replaced cannot claim. A claim by a driver bound to the item under the procedures it started with is judged under those procedures.

Dependencies gate by lane: a parent prepared (or delivered) clears the preparation of its dependents, a delivered parent clears their work, a task parent must be delivered for both, and a holder counts through its children. A parent whose stored phase reads as preparation does not clear a dependent's preparation.

### The child command

`telec todo child <item>` starts the child procedure the holding driver's declarations name, with the role, parameters and launch defaults those declarations give, as a session in the driver's claiming group. It refuses a caller that does not hold the item, or that is releasing it. The start is recorded on the item before the session is created, so the act that releases the claim accounts for it. The declarations a driver started under are carried by the platform from its own record, never supplied by the caller. The child is that of the phase's scope: a scope that names none, as the work procedure's `ready` scope, is refused naming that none exists.

The declared child is the phase's producer. The driver starts its dedicated
reviewer through the existing `telec sessions run` helper surface under
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`, Helpers of a driver; this command gains no reviewer selector.

### Use cases

#### UC-IA1: An act is recorded with the identity of the session that performed it

```gherkin
Given a session holding an item and a note it wants to leave
When the session performs the note act
Then the log shows the note with the time, the session and the role the platform authenticated
And prose in the note that claims a role, session or act creates none and changes the attribution of nothing
```

#### UC-IA2: A refused act names what it needs and writes nothing

```gherkin
Given an act that requires the holder, a builder in the holder's group, or the person the item waits on
When any other session performs it
Then the refusal names the act and the performer it requires
And the item's phase, log and attributed notices are unchanged
```

#### UC-IA3: A finding is addressable by its reply

```gherkin
Given the work driver places a finding against a commit
When the command reports the finding's key
Then a builder in the holder's group can reply naming that key
And the finding is answered for every session
```

#### UC-IA4: An interrupted act completes when repeated

```gherkin
Given an act that was interrupted after some of its writes landed
When the same act is performed again
Then the missing writes complete
And no note, stamp or notice is recorded twice
```

#### UC-IA5: A stamp whose gates are running is not run twice

```gherkin
Given the stamp act is running its build gates as an operation
When the same stamp is submitted again, including by a caller that stopped waiting for the first
Then the second submission attaches to the running operation
And the gates run once
And a stamp that asks for something else while the first runs is refused without displacing it
```

#### UC-IA6: The child starts from the driver's own declarations

```gherkin
Given a driver that started before a published change to its procedure's declarations
When the driver starts its child
Then the child carries the role, parameters and launch defaults of the declarations the driver started under
And the child is in the driver's claiming group
```

#### UC-IA7: An entry verb that cannot start a driver names the cause

```gherkin
Given an item that is held, waiting on a person, in a phase another verb drives, blocked by dependencies, or prepared at a body revision that has since changed
When a session calls the entry verb
Then the verb refuses naming that one cause
And the item is unchanged
```

#### UC-IA8: A caller that stops waiting for a driver start does not start a second

```gherkin
Given an entry verb that is still starting a driver
When its caller stops waiting and the verb is called again
Then the second call attaches to the start in progress
And exactly one driver session exists
```

#### UC-IA9: A decision answers the wait it names

```gherkin
Given an item waiting on a person with an open wait
When the person's own session decides, naming that wait
Then the answer is recorded for that wait and the waiting clears
And repeating the same decision after the item opened a later wait reports the first as finished and answers nothing else
And a decision naming a wait that is not the open one is refused and clears nothing
```

#### UC-IA10: A driver whose start was released cannot claim

```gherkin
Given a driver that was started for a request that has since been released or replaced
When the driver tries to claim by presenting that request's reservation
Then the claim is refused naming that no start is awaiting it, or that it was started for another request
And the item is unchanged
```

## Known caveats

- A driver start that never completes does not release the item by elapsed time. A start is released only on the platform's own durable evidence for exactly that request: the activation consumer has handled the request event, every activation it accepted for that event is terminal, and no open session is bound to the item for the procedure and home of any of them. The activations are recorded on the reservation while the platform still holds their receipts, within three days of the request; a start whose activations were not captured in that window stays unknown and held, and is not released by this rule.
- Which reservation a driver presents is the one carried by the request event that activated it. The entry commands that take it are the machine's, not the person's.

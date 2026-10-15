---
description: The sealed commands through which sessions perform the acts of an item's lifecycle - the act command with its per-act parameters, the entry verbs' results, and the child launch.
delivered_by:
  - issue-128
---

# Item Acts — Spec

## What it is

A session performs the acts of an item's lifecycle through one sealed act command, starts a phase's driver through the entry verbs, and starts a driver's child through the child command. The vocabularies of phases and acts and the rule for who may perform each act are `local/projects/teleclaude/spec/feature/workflow/item-lifecycle`; what connects the work driver and the builder is `local/projects/teleclaude/spec/feature/workflow/work-review-cycle`; the mechanism is `local/projects/teleclaude/design/architecture/workflow-machine`.

The procedures name each act by its capability. The instruction an entry verb returns names the command that performs it for the project's store, so a procedure reads the same on every store. On a project whose store is local, the command is the one below.

Facing: every actor is an agent session. The person reads the result through the item's log and notices.

## Canonical fields

### The act command

`telec todo act <item> <act> [<text>]` performs one act on the item named by its identity. The caller's role and session come from the authenticated session. The `<act>` argument is a value of the closed act vocabulary that the command validates, and `<item>` and `--person` name identities that the command resolves and checks. Prose the caller writes, including text shaped like a header or an envelope, supplies no role, session or act.

| Act        | Required              | Text                | Records                                                         |
| ---------- | --------------------- | ------------------- | --------------------------------------------------------------- |
| `note`     | the text              | the note            | a note in the log; moves nothing                                |
| `reviewed` | `--sha <commit>`      | optional summary    | the commit as examined by the driver                            |
| `finding`  | `--sha <commit>`      | the finding         | a finding bound to the commit; the result names its finding key |
| `reply`    | `--finding <key>`     | the reply           | an answer to that finding                                       |
| `prepared` | `--revision <digest>` | optional summary    | the item prepared at that body revision                         |
| `waiting`  | `--person <slug>`     | the question        | the item waiting on that person                                 |
| `decision` | the text              | the person's answer | the person's answer; the waiting clears                         |
| `stamp`    | `--sha <commit>`      | optional summary    | a stamp bound to that commit                                    |
| `kickback` | the text              | the reason          | the item returned to preparation                                |
| `release`  | none                  | none                | the holder's claim released                                     |

The acts `create`, `claim`, the intent-body edit and `delivered` are performed through their own surfaces: the create verb, the entry verbs, the artifact write verb under the claiming group's authority, and the integrator.

A successful act prints its act key, the item's phase afterwards and whether every effect of the act finished. A refused act prints the act and the performer it requires, or the precondition that failed - the two revisions that differ, the refs that disagree, the failing gate, the person with no authority over the project - and writes nothing.

An act repeated after an interruption, or by a caller that stopped waiting, completes what is missing and writes nothing twice; a repetition of a finished act reports it finished. The stamp runs its gates once per invocation: repeating it while it runs attaches to the running invocation.

Every act is appended to the item's log as prose that a person can follow, with the time, the role, the session and the act.

### The entry verbs

`telec todo prepare <item>` and `telec todo work <item>` call the machine. Called by a session that does not hold the item, a verb completes with the session of the driver it started, or refuses with one cause: held by a session, waiting on a person, the phase and the verb that drives it, unmet dependencies, or a body revision that no longer matches. A caller that stops waiting leaves the start running, and repeating the verb attaches to it. Called by the holding driver, a verb returns the instruction for the phase.

### The child command

`telec todo child <item>` starts the child procedure the holding driver's declarations name, with the role, parameters and launch defaults those declarations give, as a session in the driver's claiming group. It refuses a caller that does not hold the item.

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
Given the stamp act is running its build gates
When the same stamp is performed again, including by a caller that stopped waiting for the first
Then the second invocation attaches to the running one
And the gates run once
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

## Known caveats

- A driver start that never completes does not release the item by elapsed time: the start is released only on evidence that its activation ended or its session ended without claiming.

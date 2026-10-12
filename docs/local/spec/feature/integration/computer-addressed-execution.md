---
description: A command addressed to another computer executes on that computer and returns that computer's answer — every daemon-backed command alike, read or write, with the owner's own clearance, refusals and receipts.
visibility: internal
delivered_by:
  - relay-computer-addressed-requests
---

# Computer-Addressed Execution — Spec

## What it is

A person or agent working from one computer acts on objects other computers own:
a todo and its artifacts in a project there, a session running there, an
operation recorded there. Addressing a command to that computer is enough. The
command executes on the computer that owns the object and the caller receives
exactly what that computer answered — its result, its receipt, or its refusal.

**One rule for every command.** Every daemon-backed command accepts the computer
to address, and the daemon decides where a request runs in one place, before
any route is reached. A request that names another computer is carried whole to
that computer and runs there through the same route a request made on that
computer runs through. A request that names this computer, or none, runs here.
No command opts into this, so a newly added command cannot miss it. A command
run from a project's checkout and addressed to another computer acts on that same
registered project there; a computer that holds no such project refuses it,
naming the project and the computer.

**Decided by the owner.** Whether the caller may perform the command is
decided by the owning computer from the caller's principal
(`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).

**Nothing is lost on the way back.** The caller receives the owning computer's
response as that computer produced it: a read's content, a receipt that names
the owning computer, or its refusal. A
receipt-backed operation is owned where it runs, and its outcome reaches the
caller the way every operation outcome does
(`local/projects/teleclaude/spec/feature/agent_runtime/durable-operation-outcomes`).

**A computer that cannot take the request says so.** An addressed computer that
is offline, unknown, or running a version that cannot carry the request produces
an error that names the computer and the reason — an offline computer as one that
did not answer — and nothing runs anywhere.

**Outside the rule.** A request about the caller's own session or about the
daemon itself names no computer. Commands that act on the invoking checkout —
code, formatting, and registering the folder they are invoked in as a project —
run where they are invoked. A configuration command acts on state a computer
owns and accepts the computer like every other command. Connection projection
and bootstrap reads serve the daemon's consolidated view and name no computer.
Opening or closing a direct conversation with a session on another computer is
not carried to that computer
(`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`).

## Canonical fields

### Use cases

#### UC-CAE1: A command addressed to another computer runs there and returns its answer

```gherkin
Given an agent session on one computer
And a todo in a project on another computer
When the agent runs a todo command addressed to that other computer — a read of the todo or one of its artifacts, or a lifecycle action on it
Then the command executes on the other computer against that computer's project
And the agent receives the result that computer produced
And nothing is created, read, or changed on the agent's own computer in its place
```

#### UC-CAE2: The owning computer's refusal reaches the caller as the refusal

```gherkin
Given a human operator addresses an action to a todo on another computer
And that todo's state does not allow the action
When the action reaches the other computer
Then the operator receives the other computer's refusal as that computer produced it
```

#### UC-CAE3: A receipt-backed operation addressed to another computer is owned there

```gherkin
Given an agent session addresses a lifecycle operation to a todo on another computer
When the other computer accepts the operation
Then the agent receives that computer's receipt, which names that computer
And the operation runs, is recorded, and reaches its terminal state on that computer
And the agent reads the operation's record on the computer the receipt names
```

#### UC-CAE5: An addressed computer that cannot take the request produces a named error

```gherkin
Scenario Outline: The caller learns which computer could not take the request and why
  Given a caller addresses a command to a computer that is <condition>
  When the command is submitted
  Then the caller receives an error naming that computer and stating that it <reported>
  And nothing is executed on any computer

  Examples:
    | condition                                      | reported                       |
    | offline                                        | did not answer                 |
    | unknown to this computer                       | is unknown                     |
    | running a version that cannot take the request | runs a build that cannot take it |
```

#### UC-CAE6: A command addressed to this computer, or to none, runs here

```gherkin
Given a caller on a computer
When the caller runs a daemon-backed command naming that same computer, or naming no computer
Then the command runs on that computer as it always has
And no request crosses to any other computer
```

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
No command opts into this, so a newly added command cannot miss it.

**Authenticated once, decided by the owner.** The caller is authenticated and
cleared once, at the edge that serves it; the request carries the caller's
principal and nothing else about who they are. The owning computer resolves that
principal's roles from its own registry and configuration, applies the command's
person band and the object's rules, judges the object from its own state, and
answers with its own result or refusal
(`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).
No login or session on the owning computer is needed or consulted. The relaying
computer neither pre-authorizes nor substitutes; it executes nothing locally in
the owner's place.

**Nothing is lost on the way back.** The caller receives the owning computer's
response as that computer produced it: a read's content, a receipt that names
the owning computer, a work refusal with its explanation and way forward. A
receipt-backed operation is owned where it runs, and its outcome reaches the
caller the way every operation outcome does
(`local/projects/teleclaude/spec/feature/agent_runtime/durable-operation-outcomes`).

**A computer that cannot take the request says so.** An addressed computer that
is offline, unknown, or running a version that cannot carry the request produces
an error that names the computer and the reason, and nothing runs anywhere.

**Outside the rule.** A request about the caller's own session or about the
daemon itself names no computer. Commands that act on the invoking checkout
without the daemon — code, formatting, local configuration — run where they are
invoked. Connection projection and bootstrap reads serve the daemon's
consolidated view and name no computer.

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
Then the operator receives the other computer's refusal, with its explanation and the way forward
And the refusal is presented as a work refusal, not recorded as a technical fault
```

#### UC-CAE3: A receipt-backed operation addressed to another computer is owned there

```gherkin
Given an agent session addresses a lifecycle operation to a todo on another computer
When the other computer accepts the operation
Then the agent receives that computer's receipt, which names that computer
And the operation runs, is recorded, and reaches its terminal state on that computer
And the operation's outcome is delivered to the agent's session the way every operation outcome is
And the agent reads the operation's record on the computer the receipt names
```

#### UC-CAE4: The owning computer decides the person band from the relayed principal

```gherkin
Given a person authenticated at a terminal on one computer and holding no login on another
And that person holds a role on the other computer that admits an action there
When the person addresses the action to the other computer
Then the other computer admits it from the person's principal and the role it resolves for them
And no login on the other computer is asked for
When the same person addresses an action the role they hold there does not admit
Then the other computer refuses it, naming the role it resolved
And no role the person holds on their own computer is consulted by the other computer
```

#### UC-CAE5: An addressed computer that cannot take the request produces a named error

```gherkin
Scenario Outline: The caller learns which computer could not take the request and why
  Given a caller addresses a command to a computer that is <condition>
  When the command is submitted
  Then the caller receives an error naming that computer and that it is <condition>
  And nothing is executed on any computer

  Examples:
    | condition                                      |
    | offline                                        |
    | unknown to this computer                       |
    | running a version that cannot take the request |
```

#### UC-CAE6: A command addressed to this computer, or to none, runs here

```gherkin
Given a caller on a computer
When the caller runs a daemon-backed command naming that same computer, or naming no computer
Then the command runs on that computer as it always has
And no request crosses to any other computer
```

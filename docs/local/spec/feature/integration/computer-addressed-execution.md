---
description: A command addressed to another computer executes on that computer and
  returns that computer's answer — every daemon-backed command alike, read or write,
  with the owner's own clearance, refusals and receipts.
visibility: internal
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
did not answer — and nothing runs anywhere: an offline computer refuses the request
when it reads it after the request's deadline.

<!-- planned:cluster-redis-outage-store-and-forward -->

**A computer cut off from the cluster says so at once.** While the requesting
computer cannot reach the cluster Redis, a request addressed to another
computer fails immediately, without waiting out its deadline, with an error
that names the computer and the unreachable cluster Redis as the reason, and
nothing runs anywhere. A person-addressed message is the one request that waits
instead (`local/projects/teleclaude/spec/messaging`, The master sends).

<!-- /planned:cluster-redis-outage-store-and-forward -->

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

#### UC-CAE1: A person can work on project tasks held by another computer

```gherkin
Scenario: Work on a remote todo through the computer that owns its project
  Given a person has a todo in a project on another computer
  When they ask their agent to read or change that todo or one of its artifacts
  Then the operation runs on the computer that owns the project
  And the person receives that computer's result, receipt, or refusal
  And nothing is created, read, or changed on the person's own computer in its place

Scenario: The remote owner explains why a todo action is refused
  Given a person asks their agent to perform an action on a remote todo
  And that todo's state does not allow the action
  When the owning computer handles the request
  Then the person receives that computer's refusal as it produced it

Scenario Outline: The person learns when a remote computer cannot take the request
  Given a person asks their agent to act on a project on another computer
  And that computer is <condition>
  When the request is sent
  Then the person receives an error naming the computer and explaining that it <reason>
  And the operation does not run on any computer

  Examples:
    | condition                                      | reason                        |
    | offline                                        | did not answer                |
    | unknown to this computer                       | is unknown                    |
    | running a version that cannot take the request | cannot carry the request      |
```

#### UC-CAE2: The owning computer's refusal reaches the caller as the refusal

#### UC-CAE3: A receipt-backed operation addressed to another computer is owned there

#### UC-CAE5: An addressed computer that cannot take the request produces a named error

#### UC-CAE6: A command addressed to this computer, or to none, runs here

#### UC-CAE7: A command the other computer fails or refuses leaves that computer answering

---
description: Any agent that recognises personal work starts that person's assistant with a brief alone; the destination is derived from the authenticated caller, and the launched assistant has no parent and ends itself.
delivered_by:
  - personal-assistant-launch
---

# Person Workspace Dispatch — Spec

## What it is

Person workspace dispatch is how an agent session that recognises work belonging
to a person starts that person's assistant without working out where to point
it. The session invokes `telec sessions run-pa "<brief>"` — a sibling of `run`
and `start` — and the session it starts lands in that person's own workspace
carrying the brief.

The caller supplies a brief and nothing else. The person, the workspace, and the
computer are derived from the authenticated caller, and the surface exposes no
parameter naming a person in any form. A platform admin's invocation takes the
same single form and reaches that admin's own workspace. A caller that resolves
to no person is refused rather than defaulted.

The launch is a convenience route, not the only one. The general session verbs
start a session in a person's workspace exactly as they do in any other folder.

The session the launch starts has no parent. Nothing waits on it and nothing
decides its ending but itself; it tells the person what it did by sending a
message and then ends. It receives the brief as a request made in the moment, so
work a schedule owns stays with that schedule (`personal/policy/assistant-conduct`).

## Canonical fields

### Use cases

#### UC-PWD1: An agent starts a person's assistant with only a brief

```gherkin
Given an agent session is authenticated and resolves to a person
When that agent invokes the personal-assistant launch command with a brief
Then a new agent session starts in that person's own workspace
And the session receives the brief as its opening instruction
And the agent supplied no path, no subfolder, no computer, and no person
```

#### UC-PWD2: The launch surface offers no way to name a person

```gherkin
Given an agent inspects the personal-assistant launch command
When the agent reads its accepted arguments
Then the brief is the only value the command accepts
And no argument, flag, or alternate form names a person
And an invocation that attempts to name a person is rejected rather than honored or ignored
```

#### UC-PWD3: Platform authority does not widen the call

```gherkin
Given an authenticated agent session whose caller holds the platform administrator role
When that agent invokes the personal-assistant launch command
Then the session starts in the administrator's own person workspace
And the command behaves identically to any other caller's invocation
And no other person's workspace becomes reachable through the launch by virtue of that role
```

#### UC-PWD4: A caller that resolves to no person is refused

```gherkin
Given an authenticated session whose caller resolves to no person
When that session invokes the personal-assistant launch command
Then the launch is refused
And the refusal states that no person could be resolved for the caller
And no session is started in any person's workspace
```

#### UC-PWD5: The general session verbs still reach a person workspace

```gherkin
Given an agent or operator invokes a general session-start or session-run command
When the requested destination is a folder inside a person's workspace
Then a session starts at that destination exactly as it would in any other folder
And nothing refuses the request because of whose workspace it is
```

#### UC-PWD6: The launch names no procedure

```gherkin
Given an agent recognises work that belongs to a person
When it invokes the personal-assistant launch command
Then it states the need in the brief and names no command or procedure to run
And the launched session determines for itself which of the person's procedures the brief calls for
```

#### UC-PWD7: The launched session has no parent and ends itself

```gherkin
Given an agent invokes the personal-assistant launch command
When the session it starts finishes the work the brief described
Then no parent was recorded for that session
And the session ends itself rather than waiting to be ended
And anything the person needs to see was delivered as a message rather than as a result a caller collects
```

#### UC-PWD8: The brief arrives as an in-the-moment request

```gherkin
Given a person's recurring work is owned by a schedule
When an agent invokes the personal-assistant launch command with a brief that would touch that work
Then the launched session receives the brief together with the statement that it is an in-the-moment request
And it handles the brief under the schedule rule (`personal/policy/assistant-conduct`) rather than as the recurring work itself
```

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the conduct an assistant follows once it has arrived, including the location gate, the ending rule, and the schedule rule the launch's framing invokes.
- docs/local/design/architecture/ai-to-ai-dispatch.md — the dispatch flow this launch joins, and its invariants.

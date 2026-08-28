---
description: A person's workspace is reachable only through a launch call that derives its target from the authenticated caller, and the general session verbs refuse to reach one at all.
delivered_by:
  - personal-assistant-launch
---

# Person Workspace Dispatch — Spec

## What it is

Person workspace dispatch is the single door through which an agent session
reaches a person's own workspace. Any session that recognises work belonging to
a person invokes `telec sessions run-pa "<brief>"` — a sibling of `run` and
`start` — and the session it starts lands in that person's workspace carrying
the brief.

The caller supplies a brief and nothing else. The person, the workspace, and the
computer are derived from the authenticated caller, and the surface exposes no
parameter naming a person in any form. A platform admin's invocation takes the
same single form and reaches that admin's own workspace. A caller that resolves
to no person is refused rather than defaulted.

The general session verbs, which each carry a target path, refuse a destination
resolving inside a person workspace. That refusal holds whether or not the
destination belongs to the caller's own person.

The session the launch starts has no parent. Nothing waits on it and nothing
decides its ending but itself; it reports by sending a message and then ends.

## Canonical fields

### Use cases

#### UC-PWD1: An agent reaches a person's workspace with only a brief

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
And an invocation that attempts to name a person is rejected rather than honored
```

#### UC-PWD3: Platform authority does not widen the call

```gherkin
Given an authenticated agent session whose caller holds the platform administrator role
When that agent invokes the personal-assistant launch command
Then the session starts in the administrator's own person workspace
And the command behaves identically to any other caller's invocation
And no other person's workspace becomes reachable by virtue of that role
```

#### UC-PWD4: A caller that resolves to no person is refused

```gherkin
Given an authenticated session whose caller resolves to no person
When that session invokes the personal-assistant launch command
Then the launch is refused
And the refusal states that no person could be resolved for the caller
And no session is started in any person's workspace
```

#### UC-PWD5: The general session verbs cannot reach a person workspace

```gherkin
Given an agent or operator invokes a general session-start or session-run command
When the requested destination resolves inside any person's workspace
Then the request is refused and no session is started there
And the refusal names the personal-assistant launch command as the route
And the refusal applies whether or not the destination belongs to the caller's own person
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

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the conduct gates this dispatch surface enforces, including why location is the gate and why a validated person argument would be a different guarantee.
- docs/project/design/architecture/ai-to-ai-dispatch.md — the dispatch flow this launch joins, and its invariants.

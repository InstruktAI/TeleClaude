---
description: A caller starts their personal assistant with an optional brief;
  the destination is derived from the authenticated caller, and
  the launched assistant has no parent and ends itself.
---

# Person Workspace Dispatch — Spec

## What it is

Person workspace dispatch is how an agent session that recognises work belonging
to a person starts that person's assistant without working out where to point
it. The caller invokes `telec sessions run-pa` — a sibling of `run` and `start` —
and the session it starts lands in that person's own workspace. An optional brief
is passed through as the opening instruction, without added framing. Without a
brief, the assistant starts with no opening message.

The caller may supply a brief and nothing else. The person, the workspace, and the
computer are derived from the authenticated caller, and the surface exposes no
parameter naming a person in any form. A platform admin's invocation takes the
same single form and reaches that admin's own workspace. A caller that resolves
to no person is refused rather than defaulted.

The launch is a convenience route, not the only one. The general session verbs
start a session in a person's workspace exactly as they do in any other folder.

The session the launch starts has no parent. Nothing waits on it and nothing
decides its ending but itself; it tells the person what it did by sending a
message and then ends. Its conduct is governed by `personal/policy/assistant-conduct`.

## Canonical fields

### Use cases

#### UC-PWD1: An agent starts a person's assistant with only a brief

```gherkin
Scenario: Start the caller's assistant with a brief
  Given an agent session is authenticated and resolves to a person
  When that agent invokes the personal-assistant launch command with a brief
  Then a new agent session starts in that person's own workspace
  And the session receives the brief as its opening instruction
  And the agent supplied no path, no subfolder, no computer, and no person

Scenario: Refuse when no person resolves for the caller
  Given an authenticated session whose caller resolves to no person
  When it invokes the personal-assistant launch command
  Then the launch is refused with a reason that no person could be resolved
  And no session is started in any person's workspace
```

#### UC-PWD2: The launch surface offers no way to name a person

#### UC-PWD3: Platform authority does not widen the call

#### UC-PWD4: A caller that resolves to no person is refused

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
When it invokes the personal-assistant launch command with a brief
Then it states the need in the brief and names no command or procedure to run
And the launched session determines for itself which of the person's procedures the brief calls for
```

#### UC-PWD7: The launched session has no parent and ends itself

#### UC-PWD8: The brief arrives without added framing

#### UC-PWD9: A caller starts an assistant without a brief

```gherkin
Given an authenticated operator resolves to a person
When that operator invokes the personal-assistant launch command without a brief
Then an assistant session starts in that person's own workspace
And the assistant receives no opening message
```

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the conduct an assistant follows once it has arrived.
- docs/local/design/architecture/ai-to-ai-dispatch.md — the dispatch flow this launch joins, and its invariants.

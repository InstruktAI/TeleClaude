---
description: Human-directed acquisition of the single coordinator role for one project instance, carried out by an agent session on the person's request, including visible adoption, sealed refusal, and procedure entry.
visibility: internal
---

# Coordinator Role Acquisition — Spec

## What it is

Coordinator role acquisition is the agent-facing door through which a live
session, acting on a person's request, becomes the sole coordinator for one
project instance. A project instance is one project root served by one
computer's daemon. Acquisition makes the role visible in the session fleet and
directs the adopted agent into the coordination procedure; it does not create
work, select a todo, or start another session.

The singleton is enforced when a session asks to acquire the role. Multiple
sessions may reach the door, but only one live session holds the role. A
refused session receives the complete next action in the refusal response,
while the incumbent remains untouched.

A coordinator is optional. A project has one only when a person asks for it,
typically because more is happening than the people involved can oversee, and
the coordinator then takes that oversight over from them. No agent starts a
coordinator or acquires the role on its own initiative, whatever it observes
about the fleet; a project without a coordinator is a normal state, not a gap
to fill. Carrying out a person's request is agent work: the agent the person
asks may start the session that acquires the role, relaying the request, or
acquire it itself. The command help states both: a coordinator comes only when
a person asks, and an agent may carry out that request.

## Canonical fields

### Use cases

#### UC-CRA1: A person establishes the project's coordinator

```gherkin
Scenario: Establish the coordinator for an uncoordinated project
  Given an agent acts on a person's request, directly or relayed by the agent the person asked, for a project instance with no live coordinator
  When the agent acquires the coordinator role
  Then it becomes the sole live coordinator for that project
  And the session fleet shows its coordinator role and title
  And the response directs it to the coordination procedure with its required reads

Scenario: Refuse a second coordinator without disturbing the incumbent
  Given one live agent session coordinates a project instance
  And another session acting on human direction does not hold that role
  When the second session attempts to acquire the role
  Then it is refused with the sanctioned instruction to end itself if started only for coordination
  And its existing role and title remain unchanged
  And the incumbent session is untouched

Scenario: The incumbent re-enters the acquisition surface
  Given a live agent session already coordinates a project instance
  When that same session acquires the role again
  Then the request succeeds idempotently and one live coordinator remains
  And the response directs the agent to the coordination procedure
```

#### UC-CRA2: A second agent session is refused without disturbing the incumbent

#### UC-CRA3: The incumbent may re-enter through the acquisition door

#### UC-CRA4: An agent can tell when coordinator acquisition is allowed

#### UC-CRA5: Coordination procedure entry always passes through acquisition

### Cross-context references

- **identity** — command clearance admits only the roles declared for the
  acquisition surface; terminal callers without an agent session have nothing
  to adopt and are refused.
- **workflow** — a coordinator observes workflow owners but acquisition creates
  no todo, claim, lifecycle phase, or runner eligibility.

## Known caveats

- The singleton is local to a project instance. A checkout on another computer
  is served by another daemon and has its own coordinator.
- A coordinator that predates this acquisition surface has no coordinator role
  in its session record and is not discoverable by the machine gate. The
  coordination procedure's refusal discipline remains the transition safety
  net until those legacy sessions end.

## See Also

- docs/local/spec/feature/agent_runtime/session-authority.md — adoption is one of the doors after which no session stands above the coordinator.

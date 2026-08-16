---
description: Human-directed acquisition of the single coordinator role for one project instance, including visible adoption, sealed refusal, and procedure entry.
visibility: internal
---

# Coordinator Role Acquisition — Spec

## What it is

Coordinator role acquisition is the agent-facing door through which a live
session, acting on human direction, becomes the sole coordinator for one
project instance. A project instance is one project root served by one
computer's daemon. Acquisition makes the role visible in the session fleet and
directs the adopted agent into the coordination procedure; it does not create
work, select a todo, or start another session.

The singleton is enforced when a session asks to acquire the role. Multiple
sessions may reach the door, but only one live session holds the role. A
refused session receives the complete next action in the refusal response,
while the incumbent remains untouched.

## Canonical fields

### Use cases

#### UC-CRA1: An agent session acquires the coordinator role

```gherkin
Given a live agent session is acting on human direction for a project instance
And no live session coordinates that project instance
When the agent asks to acquire the coordinator role
Then that agent becomes the sole live coordinator for the project instance
And the session fleet shows that agent with the coordinator role and coordinator title
And the response directs the agent to read and follow the coordination procedure with all of its required reads
```

#### UC-CRA2: A second agent session is refused without disturbing the incumbent

```gherkin
Given one live agent session coordinates a project instance
And another live agent session for that project instance has not acquired the coordinator role
When the second agent asks to acquire the coordinator role
Then the request is refused
And the response directs a session started solely for coordination to end itself
And the second session's existing role and title remain unchanged
And the incumbent session is not changed, messaged, or assessed
```

#### UC-CRA3: The incumbent may re-enter through the acquisition door

```gherkin
Given a live agent session already coordinates a project instance
When that same agent asks to acquire the coordinator role again
Then the request succeeds idempotently
And the project instance still has exactly one live coordinator
And the response again directs the agent to the coordination procedure
```

#### UC-CRA4: The agent-facing command advertises only the guarded acquisition

```gherkin
Given an agent inspects the available session commands
When the agent reads the coordinator-acquisition command help
Then the command is described as human-directed adoption of the project's single coordinator
And the description states that acquisition refuses while a coordinator is live
And no notes or examples encourage autonomous invocation
```

#### UC-CRA5: Coordination procedure entry always passes through acquisition

```gherkin
Given a live agent session begins the coordination procedure on human direction
When the agent performs the procedure's first step
Then it asks to acquire the coordinator role before observing the fleet
And a refused agent ends itself without disturbing the incumbent
And an adopted agent continues with the remainder of the procedure
```

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

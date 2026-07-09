---
description: "Allow every non-worker system role to call `telec todo update` on a todo that is unclaimed or claimed by the caller's own session, bypassing the standard all-or-nothing role band."
visibility: 'public'
delivered_by:
  - grant-claim-scoped-todo-update-to-non-worker-roles
---

# Claim-Scoped Todo Update Authorization — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec todo update` mutates a todo's slug, dependencies, kind, hold, or runner claim. Its system band admits every system role except `worker`, and for the two non-dispatch roles in that band — `tasker` and `job_runner` — clearance is additionally scoped to the todo's claim.

The claim is the authority. A `tasker` session dispatched onto a todo holds that todo's `active_runner` lease, so it already has full legitimate authority over the todo it is actively running; refusing it the update verb forces every self-correction — reclassifying a `kind` discovered to be misfiled, recording a dependency edge — through a human or an orchestrator session for no safety gain. Scoping the exception to the claim, rather than granting the verb outright, preserves the property that no non-dispatch role mutates a todo another runner is driving.

The clearance gate admits a `tasker` or `job_runner` caller when the target todo's `active_runner` is absent or equals the caller's own `session_id`, and refuses it when a different session holds the claim. `system`, `orchestrator`, and `integrator` callers, and every human caller, are returned immediately after the standard verb-allowlist check — their access is unrestricted and reads no todo state. `worker` is excluded at the verb band itself and is refused before any claim lookup runs; the exclusion is claim-independent and holds whether the todo is claimed or not.

A non-null `active_runner` denotes a live claim: session teardown clears the field, so the gate resolves ownership from stored state without probing session liveness. The gate fails closed — a request whose body is not structured, or whose `cwd` does not resolve to a project checkout, is refused with the same not-permitted authorization failure rather than a distinguishable request error.

This carve-out follows the shape of `feature/identity/self-restart-authorization-bypass` and `feature/identity/self-end-authorization-bypass`: a bespoke clearance gate that recognises a self-scoped shape and otherwise falls through to the standard rule.

## Canonical fields

### Use cases

#### UC-CSU1: Tasker updates the todo it holds the claim on

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is `t-1`
When the session calls `telec todo update` on that todo
Then the claim-scope gate accepts (the caller owns the live claim)
And the requested mutation is applied to the todo state
```

#### UC-CSU2: Tasker updates an unclaimed todo

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim-scope gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU3: Tasker is refused on a foreign-claimed todo

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is `other-session`
When the session calls `telec todo update` on that todo
Then the claim-scope gate rejects (the claim is held by another session)
And the response is a not-permitted authorization failure for `telec todo update`
And the todo state is unchanged
```

#### UC-CSU4: Job runner updates an unclaimed todo

```
Given a job-runner agent session with system_role=`job_runner` and session_id=`j-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim-scope gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU5: Worker is refused regardless of claim state

```
Given a worker agent session with system_role=`worker` and session_id=`w-1`
And a todo whose active_runner is absent, and separately a todo whose active_runner is `w-1`
When the session calls `telec todo update` on either todo
Then the standard verb allowlist rejects the caller before any claim lookup runs
And the response is a not-permitted authorization failure for `telec todo update`
```

#### UC-CSU6: Orchestrator access stays unrestricted

```
Given an orchestrator agent session with system_role=`orchestrator`
And a todo whose active_runner is `other-session`
When the session calls `telec todo update` on that todo
Then the standard verb allowlist accepts the caller
And no claim lookup runs
And the requested mutation is applied to the todo state
```

#### UC-CSU7: Human caller access stays unrestricted

```
Given a terminal caller with system_role=None and human_role=`member`
And a todo whose active_runner is `other-session`
When the caller invokes `telec todo update` on that todo
Then the human band accepts the caller
And no claim lookup runs
And the requested mutation is applied to the todo state
```

### Cross-context references

- The verb→Role allowlist this gate narrows lives in the CLI surface schema — see `feature/identity/command-clearance`, which owns the standard rule.
- The gate reads `active_runner` from the workflow context's todo store; the workflow context owns that field and the lifecycle runner writes it when it dispatches a session onto a todo.
- Session teardown clears `active_runner`, which is what lets the gate treat a non-null claim as live without a session-liveness probe.
- `worker`'s exclusion is a property of the verb band, not of this gate — the counterpart of `feature/identity/self-restart-authorization-bypass`, where the gate itself short-circuits the worker role.

## Known caveats

- The gate reads the request body to resolve the target `slug` and `cwd`, so the body is parsed twice — once here and once by the route handler. The inbound transport caches parsed payloads; a transport variant that disables caching would fail the second read. This is the same constraint the self-restart bypass carries.
- A non-null `active_runner` is trusted as a live claim because session teardown clears it. If the daemon dies without clearing the field, the todo stays un-updatable by `tasker` and `job_runner` until the claim is released — `telec todo update --unclaim` is itself gated by this rule, so recovery runs through an orchestrator or human caller.
- `worker` is excluded at the verb band rather than by a short-circuit inside the gate. A future edit that adds `worker` to the band would silently grant it the claim-scoped exception, because the gate's claim check admits any role that reaches it.
- The gate refuses an unresolvable `cwd` with an authorization failure rather than a request error, so a `tasker` or `job_runner` caller cannot distinguish a bad project path from a foreign claim. Unrestricted roles still receive the route's own request error for the same input, because the gate returns before reading the body for them.
- `job_runner` gains the verb across every unclaimed todo, which is broader than the lineage-scoped create verbs it otherwise holds. The claim is the only boundary.

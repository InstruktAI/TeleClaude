---
description: "`telec todo update` authorization reads the object, not the caller role: every non-worker agent caller is admitted only when the target todo is unclaimed or claimed by the caller's own session."
visibility: 'public'
delivered_by:
  - grant-claim-scoped-todo-update-to-non-worker-roles
---

# Claim-Scoped Todo Update Authorization — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec todo update` mutates a todo's slug, dependencies, kind, hold, or runner claim. Its authorization reads the object: the verb's system band admits every system role except `worker`, and every admitted agent caller — dispatch-capable roles included, uniformly — is then gated on the todo's claim. No role holds unrestricted access to this verb.

The claim is the authority, enforced at the point of mutation. Inside the update route's mutation sequence — under the per-todo claim serialization that claim acquisition itself uses — the gate admits an agent caller when the target todo's `active_runner` is absent, names a session that is no longer live, or equals the caller's own `session_id`. It refuses when a different live session holds the claim, and the refusal carries the claim-conflict shape naming the holder — the caller's door is the holding session (address it, or have it release the claim), never a role it should have had. Because acquisition and enforcement share one serialization, a claim acquired after request admission still refuses the mutation.

`worker` is excluded at the verb band itself, before any claim lookup runs. The exclusion is claim-independent: it is the capability boundary that keeps a dispatched build worker inside its brief, standing in for the capability layer until that layer exists. Human (terminal/TUI/web) callers are evaluated against the verb's human band exactly as before; no gate has a human path (`general/principle/trust-and-guardrails`).

A claim held by a dead session counts as unclaimed, so a crashed holder never locks a todo. This is the same object predicate that governs prepare-artifact writes (`project/spec/feature/workflow/artifact-versioning`, Write authority); the verb adopts that predicate rather than defining a sibling. The build-started freeze on slug and kind mutation is a separate phase invariant and is unchanged by this contract.

## Canonical fields

### Use cases

#### UC-CSU1: Tasker updates the todo it holds the claim on

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is `t-1`
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the caller owns the live claim)
And the requested mutation is applied to the todo state
```

#### UC-CSU2: Tasker updates an unclaimed todo

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU3: Tasker is refused on a foreign-claimed todo

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner names a different live session
When the session calls `telec todo update` on that todo
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU4: Job runner updates an unclaimed todo

```
Given a job-runner agent session with system_role=`job_runner` and session_id=`j-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU5: Worker is refused regardless of claim state

```
Given a worker agent session with system_role=`worker` and session_id=`w-1`
And a todo whose active_runner is absent, and separately a todo whose active_runner is `w-1`
When the session calls `telec todo update` on either todo
Then the verb band rejects the caller before any claim lookup runs
And the response is a not-permitted authorization failure for `telec todo update`
```

#### UC-CSU6: Orchestrator is refused on a foreign-claimed todo

```
Given an orchestrator agent session with system_role=`orchestrator`
And a todo whose active_runner names a different live session
When the session calls `telec todo update` on that todo
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU7: Human caller access stays unchanged

```
Given a terminal caller with system_role=None and human_role=`member`
And a todo whose active_runner names a live agent session
When the caller invokes `telec todo update` on that todo
Then the human band accepts the caller as before
And no claim lookup runs
And the requested mutation is applied to the todo state
```

#### UC-CSU8: A dead holder's claim counts as unclaimed

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner names a session that is no longer live
When the session calls `telec todo update` on that todo
Then the claim gate accepts (no live claim exists)
And the requested mutation is applied to the todo state
```

#### UC-CSU9: A claim acquired after admission refuses the mutation

```
Given an agent session's `telec todo update` request admitted for an unclaimed todo
And a different live session acquires the todo's claim before the mutation applies
When the mutation point is reached
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

### Cross-context references

- The object-based authorization model this gate instantiates is recorded in `adr/0067-authorization-reads-the-object-not-the-caller-role`.
- The claim predicate (own claim, or no live claim, passes; live foreign claim refuses as a claim conflict) is the same one governing prepare-artifact writes — see `feature/workflow/artifact-versioning`, Write authority.
- The verb→Role band this contract narrows lives in the CLI surface schema — see `feature/identity/command-clearance`.
- `active_runner` is owned by the workflow context and set by lifecycle-machine dispatch through the shared per-todo claim serialization; session teardown clears it, and the liveness check covers the teardown that never ran.
- The build-started freeze on slug/kind mutation is a phase invariant owned by the todo-management contract, orthogonal to this claim gate.

## Known caveats

- The gate holds only for the mutation sequence it wraps. Claim release is not serialized against it — a holder releasing mid-update relaxes the gate rather than tightening it, which is safe; only acquisition shares the serialization.
- `worker` is excluded at the verb band rather than inside the gate. A future edit adding `worker` to the band would silently grant it the claim-scoped access, because the gate admits any role that reaches it. The band is the capability stand-in; when the capability layer lands, the band's job moves there.
- Orchestrator-class callers hold no unrestricted access on this verb. No flow legitimately mutates a todo another live session is driving; a flow that needs to goes through the holder, not around it.
- The liveness check makes gate outcomes depend on session-registry state: a holder that dies between two identical calls changes the second call's outcome from refusal to acceptance. This is the intended reading of "unclaimed," not nondeterminism.

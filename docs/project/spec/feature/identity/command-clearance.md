---
description: "Gate every protected operation on the CLI verb's role allowlist via the command-clearance capability."
visibility: 'public'
---

# Command Clearance — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

Command clearance is v1's authorization gate. After caller verification resolves a call into a `CallerIdentity`, the clearance capability consults the CLI surface schema for the named verb (e.g. `"telec sessions start"`) and checks the caller's Role against that verb's `CommandAuth(system=..., human=...)` allowlist. Agent callers (those with a `system_role`) are evaluated against the verb's system band; terminal callers (no `system_role`) are evaluated against the human band. Token-auth callers without a `human_role` fall back to their token-stamped `principal_role`. Unknown verb paths fail closed. The verb→Role table lives declaratively in the CLI surface schema, so adding a new operation means adding a `CommandAuth` to the schema and binding the corresponding clearance gate.

## Canonical fields

### Use cases

```
Given a token-authenticated call from a session whose CallerIdentity has system_role=`worker` and human_role=None
And the operation is gated by command clearance for `telec sessions tail`
And the CLI surface allowlist for `sessions tail` system band contains `worker`
When the clearance gate runs
Then the gate evaluates the system band and accepts the caller
And the CallerIdentity is returned unchanged
```

```
Given the same call, but the gated operation is `telec sessions start`
And the CLI surface allowlist for `sessions start` system band does NOT contain `worker`
When the clearance gate runs
Then the gate rejects the caller with a not-permitted authorization failure naming the role and verb
```

```
Given a terminal-authenticated call whose CallerIdentity has system_role=None, human_role=`member`, email=`maurice@instrukt.ai`
And the gated operation is `telec todo prepare`
And the verb's human band includes admin + member + contributor
When the clearance gate runs
Then the gate evaluates `member` against the human band and accepts the caller
And the CallerIdentity is returned unchanged
```

```
Given a token-authenticated CallerIdentity with human_role=None and principal_role=`admin`
And the gated operation is `telec agents status` whose human band contains `admin`
When the clearance gate runs
Then principal_role substitutes for the missing human_role
And the gate evaluates `admin` against the human band and accepts the caller
```

```
Given any CallerIdentity
And a clearance gate for a verb that does not resolve to any known CLI surface entry
When the clearance gate runs
Then the verb resolver returns no match
And the gate rejects the caller (fail-closed)
```

```
Given a system-role CallerIdentity (system_role=`worker`)
And an operation whose system band is empty but whose human band contains the caller's nominal human band
When the clearance gate runs
Then only the system branch is evaluated (system_role is not None)
And the gate rejects the caller — the human band is never consulted for agent callers
```

### Cross-context references

- The verb→Role allowlist data lives in the CLI surface schema, owned by the `config`/CLI-shape concern. The identity context owns only the gate logic.
- Consumed everywhere a protected operation is bound. Each operation binding imports the per-verb clearance gate.
- The self-agent-restart carve-out adds a self-restart bypass on top of the standard rule — see `feature/identity/self-restart-authorization-bypass`.
- The self-end carve-out adds a self-end bypass on top of the standard rule, allowing a parentless session (`initiator_session_id is None`) to end itself — see `feature/identity/self-end-authorization-bypass`.

<!-- planned:grant-claim-scoped-todo-update-to-non-worker-roles -->

- The `telec todo update` gate replaces role privilege with object state for every agent caller uniformly — see the Claim-scoped todo update section below.

<!-- /planned:grant-claim-scoped-todo-update-to-non-worker-roles -->

- The token-path `principal_role` substitution interlocks with token issuance — see `feature/identity/principal-resolution` (which stamps the role onto the token at issuance time).
- In v2 this responsibility moves out of identity: each bounded context defines its own authorization rules against the resolved `Principal`'s Role. Identity returns the Principal; the bounded context decides which operations require which roles.

<!-- planned:grant-claim-scoped-todo-update-to-non-worker-roles -->

### Claim-scoped todo update

`telec todo update` replaces role privilege with object state. The verb's band admits every agent session except `worker`, and every admitted caller that carries an agent session id — dispatch-capable roles and roleless sessions included — is then gated on the todo's claim at the point of mutation. No role holds unrestricted access to this verb (ADR-0067).

The claim gate is the claiming-group predicate governing artifact writes (`feature/workflow/artifact-versioning`, Write authority; ADR-0096). A todo whose `active_runner` names a live session is claimed; its claiming group is the holding session plus every session it dispatched, transitively through `initiator_session_id`. The gate admits a caller inside the claiming group, and admits any caller on an unclaimed todo — no `active_runner`, or one naming a session that is no longer live. It refuses a caller outside a live claim's group with the claim-conflict shape naming the holding session: the caller's door is that session, never a role it should have had. The todo state is unchanged by a refused update.

The gate is evaluated at the mutation point — after request admission and validation, immediately before the update's first state write — so a claim acquired after admission and before that point refuses the update. A slug rename executes as a deferred durable operation; an agent-originated rename evaluates the gate again immediately before the physical rename and reports a conflict through the operation record. Claim acquisition is not serialized against the gate: a claim written between the evaluation and the write it guards is not seen.

`worker` is excluded at the verb band before any claim lookup runs — the claim-independent capability stand-in that keeps a dispatched build worker inside its brief. A direct human-identity caller — a login-resolved human principal carrying no agent session id — is not a session, is not gated by the claim, and is evaluated against the verb's human band as before; the claim is an integrity boundary between sessions, and this is the same caller class the artifact-write claim gate exempts (ADR-0096; `feature/workflow/artifact-versioning`, UC-WAV16, UC-WAV23). The build-started freeze on slug/kind mutation is a phase invariant owned by the todo-management contract, orthogonal to this gate.

#### UC-CSU1: A claim holder updates its todo

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is `t-1`
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the caller holds the live claim)
And the requested mutation is applied to the todo state
```

#### UC-CSU2: A session dispatched by the claim holder updates the todo

```
Given a live session `t-1` holding the claim on a todo
And a non-worker agent session `c-1` whose initiator_session_id chain reaches `t-1`
When `c-1` calls `telec todo update` on that todo
Then the claim gate accepts (the caller is inside the claiming group)
And the requested mutation is applied to the todo state
```

#### UC-CSU3: Any non-worker agent session updates an unclaimed todo

```
Given a job-runner agent session with system_role=`job_runner` and session_id=`j-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU4: A dead holder's claim counts as unclaimed

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner names a session that is no longer live
When the session calls `telec todo update` on that todo
Then the claim gate accepts (no live claim exists)
And the requested mutation is applied to the todo state
```

#### UC-CSU5: A caller outside the claiming group is refused whatever its role

```
Given an agent session with system_role=`orchestrator` (or `system`, `integrator`, `tasker`, or none)
And a todo whose active_runner names a different live session outside the caller's claiming group
When the session calls `telec todo update` on that todo
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU6: Worker is refused regardless of claim state

```
Given a worker agent session with system_role=`worker` and session_id=`w-1`
And a todo whose active_runner is absent, and separately a todo whose active_runner is `w-1`
When the session calls `telec todo update` on either todo
Then the verb band rejects the caller before any claim lookup runs
And the response is a not-permitted authorization failure for `telec todo update`
```

#### UC-CSU7: A direct human-identity caller is not claim-gated

```
Given a login-resolved human caller with human_role=`member` and no agent session id
And a todo whose active_runner names a live agent session
When the caller invokes `telec todo update` on that todo
Then the human band accepts the caller as before
And no claim gate applies
And the requested mutation is applied to the todo state
```

#### UC-CSU8: A claim acquired after admission refuses the update at the mutation point

```
Given an agent session's `telec todo update` request admitted for an unclaimed todo
And a different live session outside the caller's claiming group acquires the todo's claim after admission and before the update reaches its mutation point
When the mutation point is reached
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU9: A claim acquired before a deferred rename executes refuses the rename

```
Given an agent session's `telec todo update --slug <new>` request admitted and queued while the todo is unclaimed
And a different live session outside the caller's claiming group acquires the todo's claim before the deferred execution reaches its mutation point
When the rename operation reaches its mutation point
Then the operation completes as a claim conflict naming the holding session
And the todo keeps its original slug with every todo surface unchanged
```

<!-- /planned:grant-claim-scoped-todo-update-to-non-worker-roles -->

### Session-family and todo-list clearance

<!-- planned-change:grant-claim-scoped-todo-update-to-non-worker-roles -->

`sessions start`, `sessions revive`, and `sessions end` carry `tasker` in their system band alongside the orchestrator class; `sessions end` additionally carries the integrator. `telec todo list` carries the full agent system band — `worker`, `system`, `orchestrator`, `integrator`, and `tasker`. The todo state-machine-driving verbs (`todo prepare`, `todo work`, and the other todo-mutation verbs) do not carry `tasker`.

<!-- change:grant-claim-scoped-todo-update-to-non-worker-roles -->

`sessions start`, `sessions revive`, and `sessions end` carry `tasker` in their system band alongside the orchestrator class; `sessions end` additionally carries the integrator. `telec todo list` carries the full agent system band — `worker`, `system`, `orchestrator`, `integrator`, and `tasker`. The todo state-machine-driving verbs (`todo prepare`, `todo work`) and the other todo-mutation verbs do not carry `tasker`; `todo update` is governed by the claim-scoped rule instead.

<!-- /planned-change:grant-claim-scoped-todo-update-to-non-worker-roles -->

#### UC-CCB1: Tasker starts a session

```
Given a tasker agent session with system_role=`tasker`
And the gated operation is `telec sessions start`
When the clearance gate runs
Then the gate evaluates the system band and accepts the caller
And the CallerIdentity is returned unchanged
```

#### UC-CCB2: Tasker revives a session

```
Given a tasker agent session with system_role=`tasker`
And the gated operation is `telec sessions revive`
When the clearance gate runs
Then the gate evaluates the system band and accepts the caller
And the real revive route admits the caller past clearance
```

#### UC-CCB3: Tasker ends a session

```
Given a tasker agent session with system_role=`tasker`
And the gated operation is `telec sessions end`
When the clearance gate runs
Then the gate evaluates the system band and accepts the caller
And the CallerIdentity is returned unchanged
```

#### UC-CCB4: Tasker remains refused the state-machine-driving verbs

```
Given a tasker agent session with system_role=`tasker`
And the gated operation is `telec todo prepare`
When the clearance gate runs
Then the gate rejects the caller with a not-permitted authorization failure naming the role and verb
```

## Known caveats

- The authorization-failure message echoes the caller's role back to the wire: `"role '<role>' is not permitted to call <tool>"`. This is helpful for diagnostics but exposes the role taxonomy to any unauthenticated probe.
- Admin is NOT implicit. The "all human roles" band lists `admin` explicitly alongside the other human roles. A future band that forgets to include `admin` will lock admins out of that verb — there is no automatic override.
- Agent callers check only the system band. A `CallerIdentity` with `system_role=worker` and a permissive `human_role` cannot fall through to the human band — the allowlist evaluator returns immediately on the system branch.
- The `principal_role` fallback fires only when `human_role is None and identity.principal is not None`. A token-auth caller carrying both a `human_role` and a `principal_role` uses the human one; the two should agree (both are stamped from the same session at issuance) but the code does not enforce equality.
- Unknown verb paths return False. A typo in a binding's verb argument silently locks out every caller — there is no startup-time check that every verb identifier resolves to a real entry in the CLI surface.
- The verb resolver normalizes `"telec sessions start"`, `"sessions.start"`, and `"sessions start"` to the same path. Mixed forms across operation bindings do not cause divergence, but the dot form is undocumented.

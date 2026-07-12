---
description: "Gate every protected operation on the CLI verb's role allowlist via the command-clearance capability."
visibility: 'public'
---

# Command Clearance — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

Command clearance is v1's authorization gate. After caller verification resolves a call into a `CallerIdentity`, the clearance capability consults the CLI surface schema for the named verb (e.g. `"telec sessions start"`) and checks the caller's Role against that verb's `CommandAuth(system=..., human=...)` allowlist. Agent callers (those with a `system_role`) are evaluated against the verb's system band; terminal/web callers (no `system_role`) are evaluated against the human band. Token-auth callers without a `human_role` fall back to their token-stamped `principal_role`. Unknown verb paths fail closed. The verb→Role table lives declaratively in the CLI surface schema, so adding a new operation means adding a `CommandAuth` to the schema and binding the corresponding clearance gate.

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

`telec todo update` narrows the standard rule with object state for every agent caller uniformly: the verb's system band admits every system role except `worker`, and every admitted agent caller — dispatch-capable roles included — is then gated on the todo's claim at the point of mutation. No role holds unrestricted access to this verb.

Inside the update route's mutation sequence — under the per-todo claim serialization that claim acquisition itself uses — the gate admits an agent caller when the target todo's `active_runner` is absent, names a session that is no longer live, or equals the caller's own `session_id`. It refuses a live foreign claim with the claim-conflict shape naming the holder: the caller's door is the holding session, never a role it should have had. Because acquisition and enforcement share one serialization, a claim acquired after request admission still refuses the mutation. A slug rename requested through the verb executes as a deferred durable operation; for an agent-originated request that execution acquires the same serialization and revalidates the claim immediately before the physical rename, reporting a late conflict through the operation record. The operation's caller classification derives from its persisted caller session id — present means agent-originated, absent means human-originated — since agent callers always carry a token-bound session id and human callers never do. A human-originated rename carries no claim gate on either side of the operation boundary — the human band admits it whole. Every claim-conflict refusal emits a structured warning naming the operation, the slug, the caller session id, and the full holder session id — the response is user feedback, the log line is the audit record.

`worker` is excluded at the verb band before any claim lookup runs — the claim-independent capability stand-in that keeps a dispatched build worker inside its brief. Human callers are evaluated against the verb's human band exactly as before; no gate has a human path (`general/principle/trust-and-guardrails`). The claim predicate is the same one governing prepare-artifact writes (`feature/workflow/artifact-versioning`, Write authority). The build-started freeze on slug/kind mutation is a phase invariant owned by the todo-management contract, orthogonal to this gate. The gate holds only for the span it wraps: claim release is not serialized against it — a holder releasing mid-update relaxes the gate, which is safe; only acquisition shares the serialization.

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

#### UC-CSU9: A claim acquired after admission refuses the update at the mutation point

```
Given an agent session's `telec todo update` request admitted for an unclaimed todo
And a different live session acquires the todo's claim through the platform's claim-acquisition surface after admission and before the mutation applies
When the mutation point is reached
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU10: A claim acquired before the deferred rename executes refuses the rename

```
Given an agent session's `telec todo update --slug <new>` request admitted and queued while the todo is unclaimed
And a different live session acquires the todo's claim through the platform's claim-acquisition surface before the deferred execution reaches its mutation point
When the rename operation reaches its mutation point
Then the operation completes as a claim conflict naming the holding session
And the todo keeps its original slug with every todo surface unchanged
```

<!-- /planned:grant-claim-scoped-todo-update-to-non-worker-roles -->

## Known caveats

- The authorization-failure message echoes the caller's role back to the wire: `"role '<role>' is not permitted to call <tool>"`. This is helpful for diagnostics but exposes the role taxonomy to any unauthenticated probe.
- Admin is NOT implicit. The "all human roles" band lists `admin` explicitly alongside the other human roles. A future band that forgets to include `admin` will lock admins out of that verb — there is no automatic override.
- Agent callers check only the system band. A `CallerIdentity` with `system_role=worker` and a permissive `human_role` cannot fall through to the human band — the allowlist evaluator returns immediately on the system branch.
- The `principal_role` fallback fires only when `human_role is None and identity.principal is not None`. A token-auth caller carrying both a `human_role` and a `principal_role` uses the human one; the two should agree (both are stamped from the same session at issuance) but the code does not enforce equality.
- Unknown verb paths return False. A typo in a binding's verb argument silently locks out every caller — there is no startup-time check that every verb identifier resolves to a real entry in the CLI surface.
- The verb resolver normalizes `"telec sessions start"`, `"sessions.start"`, and `"sessions start"` to the same path. Mixed forms across operation bindings do not cause divergence, but the dot form is undocumented.

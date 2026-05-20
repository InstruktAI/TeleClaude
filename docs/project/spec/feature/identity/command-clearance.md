---
id: 'project/spec/feature/identity/command-clearance'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Gate every protected daemon route on the CLI verb''s role allowlist via the `require_clearance(tool_name)` dependency.'
---

# Command Clearance — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`require_clearance(tool_name)` is v1's authorization gate. After `verify_caller` resolves a request into a `CallerIdentity`, the clearance dependency consults the CLI surface schema for the named verb (e.g. `"telec sessions start"`) and checks the caller's Role against that verb's `CommandAuth(system=..., human=...)` allowlist. Agent callers (those with a `system_role`) are evaluated against the verb's system band; terminal/web callers (no `system_role`) are evaluated against the human band. Token-auth callers without a `human_role` fall back to their token-stamped `principal_role`. Unknown verb paths fail closed. The verb→Role table lives declaratively in the CLI surface, so adding a new route means adding a `CommandAuth` to the schema and binding the corresponding pre-built `clearance_*` dependency.

## Canonical fields

### Use cases

```
Given a token-authenticated request from a session whose CallerIdentity has system_role=`worker` and human_role=None
And the route is gated by `clearance_sessions_tail = require_clearance("telec sessions tail")`
And `CLI_SURFACE["sessions"].subcommands["tail"].auth.system` contains `worker`
When the dependency runs
Then `is_command_allowed` resolves the command path and calls `CommandAuth.allows`
And `allows` checks `worker in auth.system` → True
And the dependency returns the CallerIdentity unchanged
```

```
Given the same request, but the gated route is `clearance_sessions_start = require_clearance("telec sessions start")`
And `CLI_SURFACE["sessions"].subcommands["start"].auth.system` does NOT contain `worker`
When the dependency runs
Then `CommandAuth.allows` returns False
And the dependency raises HTTPException(403, "role 'worker' is not permitted to call telec sessions start")
```

```
Given a terminal-authenticated request whose CallerIdentity has system_role=None, human_role=`member`, email=`maurice@instrukt.ai`
And the route is `clearance_todos_prepare = require_clearance("telec todo prepare")`
And the verb's `auth.human` set is `_HR_MEMBER_CONTRIB` (admin + member + contributor)
When the dependency runs
Then `CommandAuth.allows` checks `member in auth.human` → True
And the CallerIdentity is returned unchanged
```

```
Given a token-authenticated CallerIdentity with human_role=None and principal_role=`admin`
And the route is `clearance_agents_status = require_clearance("telec agents status")` with `auth.human` containing `admin`
When the dependency runs
Then `_is_tool_denied` substitutes principal_role for the missing human_role
And `CommandAuth.allows` checks `admin in auth.human` → True
And the call passes
```

```
Given any CallerIdentity
And a `require_clearance("telec nonexistent verb")` dependency
When the dependency runs
Then `_resolve_command_auth` returns None (unknown command path)
And `is_command_allowed` returns False (fail-closed)
And the dependency raises HTTPException(403)
```

```
Given a system-role CallerIdentity (system_role=`worker`)
And a route whose `CommandAuth.system` is empty but whose `CommandAuth.human` contains the caller's nominal human band
When the dependency runs
Then `CommandAuth.allows` evaluates ONLY the system branch (system_role is not None)
And returns False — the human band is never consulted for agent callers
```

### Implementation pointers (v1)

- Dependency factory: `teleclaude/api/auth.py:304-326` (`require_clearance`)
- Denial check with principal_role fallback: `teleclaude/api/auth.py:296-301` (`_is_tool_denied`)
- Command-path resolver: `teleclaude/cli/telec/auth.py:8-26` (`_resolve_command_auth`)
- Public predicate: `teleclaude/cli/telec/auth.py:29-43` (`is_command_allowed`)
- Allowlist evaluator: `teleclaude/cli/telec/surface_types.py:59-67` (`CommandAuth.allows`)
- Role band constants (`_HR_ADMIN`, `_HR_MEMBER`, `_HR_MEMBER_CONTRIB`, `_HR_ALL`, etc.): `teleclaude/cli/telec/surface_types.py:171-180`
- System role bands (`_SYS_ORCH`, `_SYS_ALL`, `_SYS_INTG`): `teleclaude/cli/telec/surface_types.py:167-169`
- Pre-built per-verb clearance dependencies (`clearance_sessions_start`, `clearance_todos_prepare`, …): `teleclaude/api/auth.py:361-390`

### Cross-context references

- The verb→Role allowlist data lives in the CLI surface (`CLI_SURFACE` in `teleclaude/cli/telec/surface.py`), which is a `config`/CLI-shape concern. Identity owns only the gate logic.
- Consumed everywhere a daemon route is protected. The pre-built dependencies in `teleclaude/api/auth.py` are imported by each route module.
- The `clearance_sessions_agent_restart` carve-out adds a self-restart bypass on top of the standard rule — see `feature/identity/self-restart-authorization-bypass`.
- The token-path `principal_role` substitution interlocks with token issuance — see `feature/identity/principal-resolution` (which stamps the role onto the token at issuance time).
- In v2 this responsibility moves out of identity: each service defines its own authorization rules against the resolved `Principal`'s Role. Identity returns the Principal; the service decides which operations require which roles.

## Known caveats

- The 403 message echoes the caller's role to the wire: `"role '<role>' is not permitted to call <tool>"`. This is helpful for diagnostics but exposes the role taxonomy to any unauthenticated probe.
- Admin is NOT implicit. The `_HR_ALL` constant lists `admin` explicitly alongside the other human roles. A future band that forgets to include `admin` will lock admins out of that verb — there is no automatic override.
- Agent callers check only the system band. A `CallerIdentity` with `system_role=worker` and a permissive `human_role` cannot fall through to the human band — `CommandAuth.allows` returns immediately on the system branch.
- The `principal_role` fallback fires only when `human_role is None and identity.principal is not None`. A token-auth caller carrying both a `human_role` and a `principal_role` uses the human one; the two should agree (both are stamped from the same session at issuance) but the code does not enforce equality.
- Unknown command paths return False. A typo in a route's `require_clearance("…")` argument silently locks out every caller — there is no startup-time check that every `tool_name` resolves to a real verb in `CLI_SURFACE`.
- `_resolve_command_auth` normalizes `"telec sessions start"`, `"sessions.start"`, and `"sessions start"` to the same path. Mixed forms in different routes do not cause divergence, but the dot form is undocumented in route bindings.

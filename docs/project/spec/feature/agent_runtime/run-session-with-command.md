---
description: 'Start a new agent session preloaded with a slash command as its first agent message (`telec sessions run`).'
visibility: 'public'
---

# Run Session With Command — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The run-session-with-command flow creates a brand-new agent session whose first agent input is a slash command — not a free-form user message. The CLI verb `telec sessions run --command /<cmd> --args ... --project ... --agent ... --mode ...` normalizes the request, resolves the effective agent, optionally rewrites the startup message for Codex, builds a typed launch intent that asks the agent*runtime service to start the agent and then deliver a message, and hands the request to session creation. The new session boots in its host pane with the resolved agent CLI; once the agent is ready, the rewritten startup message is delivered and polling begins. This is conceptually distinct from `sessions start` because the session is \_preloaded* with a slash-command invocation — the very first thing the agent sees is the command, not a human turn.

## Canonical fields

### Use cases

#### Agent resolution

```
Given a run-session request
When the request explicitly sets the "agent" field
Then the agent_runtime service validates the requested agent against the enabled-agent set
And rejects unknown or disabled agents with a request-rejection error
```

```
Given a run-session request that omits the "agent" field
When the agent_runtime service resolves the effective agent
Then it consults the project/system default agent
And rejects with a configuration-conflict error when no default agent is configured
```

#### Command and arguments normalization

```
Given a request with command "/next-build" and args "my-slug"
When the run-session preparation normalizes the inputs
Then leading slashes are stripped from the command token
And the full command becomes "/next-build my-slug"
And the slash command is parsed against the known slash-command set for role inference
```

```
Given a request whose command does not start with "/"
When the request is validated
Then it is rejected with "command must start with '/'"
```

```
Given a request with an empty project
When the request is validated
Then it is rejected with "project required"
```

```
Given a request whose normalized command is in the worker-lifecycle command set (next-build, next-review-build, next-fix-review, next-finalize)
And the args field is empty after trimming
When the run-session preparation validates the request
Then it is rejected with "/<command> requires a slug argument"
```

#### Codex loader-message rewrite

```
Given the effective agent is "codex"
And the normalized command starts with "next-" (e.g., "/next-build my-slug")
When the Codex startup-message rewrite runs
Then the startup message is replaced by a Codex loader prompt that
  instructs Codex to read the compiled command prompt file from the
  configured commands directory and treat the args as inputs to that
  instruction set
And the public full-command (used for the human-visible initial-input echo) remains the original "/<command> <args>" form
```

<!-- planned-change:fix-next-integrate-regression -->

```
Given the effective agent is "codex"
And the normalized command starts with "/next-"
And the args field is empty
When the Codex startup-message rewrite validates the inputs
Then it rejects with "/<command> requires a slug argument"
```

<!-- change:fix-next-integrate-regression -->

#### UC-CLR1: Codex slug-bound /next-\* with empty args is rejected

```
Given the effective agent is "codex"
And the normalized command starts with "/next-"
And the command is slug-bound (not in the non-slug-bound set: next-integrate, next-review-commits)
And the args field is empty
When the Codex startup-message rewrite validates the inputs
Then it rejects with "/<command> requires a slug argument"
```

#### UC-CLR2: Codex non-slug-bound /next-\* with empty args produces the loader message

```
Given the effective agent is "codex"
And the normalized command is in the non-slug-bound set (next-integrate, next-review-commits)
And the args field is empty
When the Codex startup-message rewrite runs
Then the startup message is replaced by a Codex loader prompt that
  instructs Codex to read the compiled command prompt file from the
  configured commands directory
And no slug argument is required
```

<!-- /planned-change:fix-next-integrate-regression -->

```
Given the effective agent is not "codex"
When the Codex rewrite runs
Then the startup message is returned unchanged
```

#### Subfolder routing

```
Given a request with subfolder="services/api"
When the agent_runtime service builds the session metadata
Then the new session's working directory is anchored under <project>/services/api
And an empty/missing subfolder leaves the subdirectory unset
```

#### Additional context propagation

```
Given a request with additional_context="<some preamble>"
When the run-session preparation assembles the launch payload
Then the additional context is appended to BOTH the echoed full-command and the startup message under the literal header "ADDITIONAL CONTEXT:"
And both Codex (post-loader-rewrite) and non-Codex agents receive the extended message
```

#### Dispatch privilege enforcement

```
Given the resolved slash command maps to a target system role
And the calling identity carries a system role of its own
When the run-session preparation checks dispatch privilege
And the target role is NOT in the caller's allowed dispatch set
Then it is rejected with "role '<caller>' cannot dispatch /<command> (requires dispatch privilege for '<target>')"
```

```
Given a caller carrying the integrator system role
When it dispatches a worker-role command (e.g. /next-review-commits for the commits it merged)
Then dispatch is permitted — the integrator may spawn worker sessions
And dispatching an orchestrator-role command is still rejected, because the integrator's grant is worker-only
```

#### Lifecycle driver-start dedup

```
Given a todo slug X already driven by a live driver — a live orchestrator bound to X, or a live active-runner recorded for X
And an orchestrator-class create request that would bind X — a run-session request whose command is "/next-prepare" or "/next-work" resolving to X, or a generic session-create on a "trees/X" worktree launching such a command
When the create-door dedup check runs before the session is created
Then the request is refused with a driver-start conflict that names the holder, returned as HTTP 409 detail
And no second session is created for X
And the refusal holds even when the requesting session is itself the holder — continuation happens in place via the operator door, never by creating a second orchestrator row
```

```
Given a todo slug X with a live active-runner recorded for X
And a task-lane create request that would bind X — a run-session or generic session-create launching "/next-run-task" for X
When the create-door dedup check runs before the session is created
Then the request is refused with a driver-start conflict that names the holder, returned as HTTP 409 detail
And no second session is created for X
```

```
Given a todo slug X already driven by a live driver
And a non-driver worker child-spawn that would bind X — a run-session or generic session-create launching a worker command such as "/next-build" or "/next-review-build" for X
When the create-door dedup check runs
Then the request is allowed and the worker session is created sharing working_slug X, because an orchestrator and the workers it spawns legitimately share the slug
```

```
Given a todo slug X already driven by a live driver from a session other than the caller
And an operator work or prepare operation on X
When the operation's shared dedup check runs
Then the operation fails with a driver-start conflict whose completion-event error carries the holder, surfacing as an operator toast
And no second session is created for X
And the caller's own slug — when the caller is itself the holder — continues in place with no new session
```

```
Given a driver-start request that would bind slug X
And no live driver yet holds X (the autonomous runner is mid-spawn establishing the first driver, before active_runner is written and before the orchestrator session exists)
When the shared driver-start dedup check runs
Then no live-holder conflict is found and the session is created
```

```
Given slug X already has a live holder
And a dispatch claim for X is still held (retained briefly after the holder's active_runner was written)
And a second orchestrator-class request for X arrives
When the shared driver-start dedup check runs
Then the live-holder signal is authoritative and the request is refused — the retained claim does not exempt it
```

#### Initiator binding

```
Given the caller identity has a session id that does not start with "web:"
When the run-session preparation captures the initiator
Then the initiator session id is recorded and propagated as the spawning-session backlink on the new session
And web-origin callers (session id prefixed "web:") do not establish an initiator link
And email-bearing identities additionally produce a web-origin metadata stamp on the new session
```

#### Launch intent + session-creation handoff

```
Given the run-session preparation has produced a run plan
When the run flow dispatches the create flow
Then it builds a create-session command via the canonical command mapper
And the launch intent kind is "agent then message" carrying the effective agent, thinking mode, and (rewritten) startup message
And the initial-input value is the original "/<command> <args>" string (for human-facing echo)
And the listener-skip flag mirrors the request's detach flag
And on success the response carries the new session id, host pane reference, and the resolved agent
```

#### Detached vs attached behavior

```
Given a request with detach=true
When the agent_runtime service creates the session
Then the listener-skip flag is true on the create-session command
And the caller's session is NOT registered as a listener on the new session
And the caller will NOT receive output forwarding from the spawned session
And the spawned session still runs the slash command normally
```

```
Given a request with detach=false (the default)
When the agent_runtime service creates the session
Then the listener-skip flag is false on the create-session command
And the caller's session is registered as a listener on the new session via the standard listener pipeline
And turn-complete output from the spawned session is forwarded back to the caller
```

#### Invalid slash command handling

```
Given a request whose command token does not match any known slash-command value
When the run-session preparation parses the token
Then no slash-command lookup succeeds
And no role inference happens (system role and job remain unset)
And dispatch privilege enforcement is skipped
And the command is still launched verbatim into the agent — agent-side handling decides whether the command is meaningful
```

### Cross-context references

- **workflow** — slash commands resolved here correspond to workflow lifecycle verbs (`/next-build`, `/next-review-build`, `/next-fix-review`, `/next-finalize`) listed in the worker-lifecycle command set. Workflow owns the slug semantics and the command-prompt artifacts that Codex's loader reads.
- **identity** — the caller identity (email, system role, session id) gates the run; the run-session clearance is the auth dependency. Web-origin identities produce web-origin metadata; terminal/agent identities form the initiator-session backlink. Dispatch privilege is an identity-domain ACL.
- **context** — the slash-command resolution surface (command + skill discovery) lives in the context bounded context. agent_runtime only validates the token shape and routes; it does not interpret command semantics.
- **config** — the default-agent and per-agent enablement gate come from the configuration-resolved enabled-agent set. The thinking mode defaults to "slow" unless supplied by the caller.

## Known caveats

- **Codex loader-message rewrite is asymmetric.** Only `/next-*` commands are rewritten for Codex; other slash commands sent to Codex pass through verbatim. The rewrite materializes the compiled prompt at `<commands-dir>/<cmd>.md` — if that file is missing on disk, Codex will fail at first read rather than at request time.
- **The full-command and the startup message diverge for Codex.** The full-command (used for the human-visible "initial input" echo) keeps the `/next-* <args>` form, while the startup message is the loader prompt. Don't infer one from the other.
- **`detach=true` does NOT cancel polling on the spawned session** — it only suppresses listener registration for the caller. The spawned session still has its own output polling and adapter routing.
- **Invalid slash commands are not rejected.** A typo in `--command` (e.g., `/nxt-build`) passes validation as long as it starts with `/` — it simply launches a session that immediately fails inside the agent. Validation here is shape-only.
- **Worker-lifecycle slug guard fires AFTER agent resolution.** A misconfigured-agent failure can mask a missing-slug error in the response; check the surface error code (slug-related vs. default-agent-related) to disambiguate.
- **`subfolder` is not validated for traversal.** The entry trusts the caller; project-path joining and subdir sanitization happen downstream in the metadata-building path.
- **Dispatch privilege depends on role inference succeeding.** If the slash command isn't canonical (typo, custom command), no role is inferred and dispatch privilege is skipped — so ACL coverage assumes the slash command is canonical.

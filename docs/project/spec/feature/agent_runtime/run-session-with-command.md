---
description: 'Start a new agent session preloaded with a slash command as its first agent message (`telec sessions run`).'
visibility: 'public'
---

# Run Session With Command — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The run-session-with-command flow creates a brand-new agent session whose first agent input is a slash command — not a free-form user message. The CLI verb `telec sessions run --command /<cmd> --args ... --path ... --agent ... --mode ...` normalizes the request, resolves the effective agent, optionally rewrites the startup message for Codex, builds a typed launch intent that asks the agent*runtime service to start the agent and then deliver a message, and hands the request to session creation. The new session boots in its host pane with the resolved agent CLI; once the agent is ready, the rewritten startup message is delivered and polling begins. This is conceptually distinct from `sessions start` because the session is \_preloaded* with a slash-command invocation — the very first thing the agent sees is the command, not a human turn.

## Canonical fields

### Use cases

#### Agent resolution

<!-- planned-change:agent-usage-aware-dispatch -->

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

<!-- change:agent-usage-aware-dispatch -->

```
Given a run-session request
And the request explicitly sets the "agent" field
When the agent_runtime service resolves the dispatch
Then it treats that field as a manual preference
And rejects unknown or disabled selected agents with a request-rejection error
```

```
Given a run-session request that omits the "agent" field
When the agent_runtime service resolves the dispatch
Then it uses the configured default agent as the preferred agent
And rejects with a configuration-conflict error when no default agent is configured
```

```
Given an automatic-preference run-session request has a preferred agent
And the preferred agent is unavailable or degraded
And another enabled agent is available for automatic dispatch
When the dispatch resolver runs
Then it selects the available fallback agent
And the response carries the selected agent
And the caller-facing output includes the reason the preferred agent was not selected
```

```
Given an automatic-preference run-session request has a preferred agent
And no enabled agent is available for automatic dispatch
When the dispatch resolver runs
Then no session is created
And the response carries a structured no-agents-available error
```

```
Given an automatic-preference run-session request has a preferred agent
And the preferred agent is enabled, available, not degraded, and below quota-pressure thresholds
When the dispatch resolver runs
Then it selects the preferred agent
```

```
Given an automatic-preference run-session request has a preferred agent
And the preferred agent is under quota pressure
And another enabled available agent has better normalized quota headroom
When the dispatch resolver runs
Then it selects the better-headroom agent
And the response carries the selected agent
And the caller-facing output includes the reason the preferred agent was not selected
```

```
Given every enabled available agent is under quota pressure
When the dispatch resolver runs
Then it selects the enabled available agent with the highest normalized quota headroom
And it does not block dispatch merely because every candidate is under pressure
```

```
Given quota data is missing, stale, or failed for every candidate
When the dispatch resolver runs
Then it preserves the existing preferred/default routing behavior
And it records diagnostic quota state without treating unknown quota as healthy
```

```
Given a run-session request supplies an agent as a manual preference
And that agent is enabled and available but under quota pressure
When the dispatch resolver runs
Then it selects the supplied agent
And quota pressure does not reroute the manual preference
```

```
Given a run-session request supplies an agent as a manual preference
And that agent is enabled, degraded, and not hard unavailable
When the dispatch resolver runs
Then it selects the supplied agent
And degraded status does not reroute the manual preference
```

```
Given a run-session request supplies an agent as a manual preference
And that agent is hard unavailable
And another enabled available agent exists
When the dispatch resolver runs
Then it selects the fallback agent
And the response carries the selected agent and the unavailable reason for the supplied agent
```

<!-- /planned-change:agent-usage-aware-dispatch -->

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
And structured lifecycle metadata such as role, job, and `working_slug` is resolved from the normalized command and args before or alongside the rewrite, never from the rewritten startup message
```

#### UC-CLR1: Codex slug-bound /next-\* with empty args is rejected

```
Given the effective agent is "codex"
And the normalized command starts with "/next-"
And the command is slug-bound (not in the non-slug-bound set: next-prepare, next-integrate, next-review-commits)
And the args field is empty
When the Codex startup-message rewrite validates the inputs
Then it rejects with "/<command> requires a slug argument"
```

#### UC-CLR2: Codex non-slug-bound /next-\* with empty args produces the loader message

```
Given the effective agent is "codex"
And the normalized command is in the non-slug-bound set (next-prepare, next-integrate, next-review-commits)
And the args field is empty
When the Codex startup-message rewrite runs
Then the startup message is replaced by a Codex loader prompt that
  instructs Codex to read the compiled command prompt file from the
  configured commands directory
And no slug argument is required
```

#### UC-CLR3: Non-Codex agent leaves the startup message unchanged

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
And an empty/missing subfolder leaves the subdirectory unset, except for a worktree-bound worker lifecycle command, whose request is rejected before any session is created
```

#### UC-SFR1: A worktree-bound worker dispatch that is not bound to the slug's worktree is rejected at the door

```
Given a run-session request whose command is a worktree-bound worker lifecycle command (next-build, next-review-build, next-finalize)
And the request resolves a working slug from its command arguments
And the request's subfolder is anything other than that slug's worktree — empty, missing, or a different path
When the run-session preparation validates the request
Then it is rejected with a detail naming the command, the resolved slug, the expected worktree subfolder, and the subfolder actually received
And no session is created
And the rejection happens at validation, so no session row is ever persisted carrying a working slug without that slug's worktree subdirectory
```

```
Given a run-session request for a worktree-bound worker lifecycle command whose subfolder is exactly the resolved slug's worktree
When the run-session preparation validates the request
Then the request is accepted
And the created session's subdirectory is that worktree, so the workflow's live-worker lookup for the slug matches it
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

#### UC-DPE1: Tasker may dispatch a worker-role session

```
Given a caller carrying the tasker system role — a /next-prepare-task or /next-run-task session
When it dispatches a worker-role command (e.g. /next-review-commits for a commit its task authored)
Then dispatch is permitted — tasker may spawn worker sessions, same grant as integrator
```

#### UC-DPE3: Tasker may not dispatch an orchestrator-role command or drive the todo state machine

```
Given a caller carrying the tasker system role
When it dispatches an orchestrator-role command (/next-prepare, /next-work)
Then it is rejected — the tasker's dispatch grant is worker-only
And tasker otherwise carries only Worker's permissions — it cannot drive the todo state machine
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

<!-- planned-change:fix-commit-review-reuse-is-prose-only-nothin -->

```
Given a todo slug X already driven by a live driver
And a non-driver worker child-spawn that would bind X — a run-session or generic session-create launching a worker command such as "/next-build" or "/next-review-build" for X
When the create-door dedup check runs
Then the request is allowed and the worker session is created sharing working_slug X, because an orchestrator and the workers it spawns legitimately share the slug
```

<!-- change:fix-commit-review-reuse-is-prose-only-nothin -->

```
Given a todo slug X already driven by a live driver
And a producing worker child-spawn that would bind X — a run-session or generic session-create launching a command such as "/next-build" or "/next-fix-review" for X
When the create-door dedup check runs
Then the request is allowed and the worker session is created sharing working_slug X, because an orchestrator and the producing workers it spawns legitimately share the slug
```

```
Given a todo slug X with a live reviewer session for review command C — one of "/next-review-build", "/next-review-plan", "/next-review-architecture"
And a create request launching that same command C for X
When the create-door dedup check runs
Then the request is refused with a driver-start conflict that names the holding reviewer session, returned as HTTP 409 detail
And no second reviewer session is created for C on X
And the refusal states the reuse command that addresses the holder instead
And a live reviewer for a different review command on X does not refuse this one, because each review phase carries its own verdict
```

<!-- /planned-change:fix-commit-review-reuse-is-prose-only-nothin -->

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

<!-- planned:fix-commit-review-reuse-is-prose-only-nothin -->

#### UC-DSD3: A second commit reviewer for the same driver and project is refused

Commit review carries no todo slug — its subject is a commit series whose SHA set changes
every remediation round — so slug-keyed dedup cannot reach it. Its subject is identified
by the project and the driver that opened the review.

```
Given a live "/next-review-commits" session for project P opened by initiator session I
And a create request launching "/next-review-commits" for project P from the same initiator I
When the create-door dedup check runs
Then the request is refused with a driver-start conflict that names the holding reviewer session, returned as HTTP 409 detail
And no second reviewer session is created
And the refusal states the reuse command that addresses the holder instead
And the refusal does not depend on the requested SHAs, which differ every remediation round
```

```
Given a live "/next-review-commits" session for project P opened by initiator session I
And a create request launching "/next-review-commits" from a different initiator, or for a different project
When the create-door dedup check runs
Then the request is allowed, because independent drivers and separate projects review independent series
```

```
Given every "/next-review-commits" session for project P and initiator I is closed
And a create request launching "/next-review-commits" for project P from initiator I
When the create-door dedup check runs
Then the request is allowed, because a closed reviewer holds nothing and the next series opens its own
```

<!-- /planned:fix-commit-review-reuse-is-prose-only-nothin -->

#### UC-DSD1: Held unclaimed lifecycle create requests are allowed but keep hold

```
Given a held todo slug X has no live holder
And an orchestrator-class create request would bind X through the New Session modal or `telec sessions run`
When the create-door dedup check runs before the session is created
Then the held flag alone does not refuse creation
And the create door does not clear hold
And hold release belongs to the lifecycle command's operator path after that path successfully claims or dispatches X
```

#### UC-DSD2: Generic create door stamps working_slug from a slash-command argument

```
Given a generic session-create request through the New Session modal or `telec sessions start`
And its initial message is a slug-bound lifecycle command such as "/next-work X" or "/next-prepare X"
When the create-door preparation normalizes the request
Then the slug is inferred from the command's argument and stamped as the create-session command's `working_slug` at creation time — the same creation-time metadata `telec sessions run` produces
And this holds without a "trees/X" worktree subdir, so a repo-root manual start binds X
And the create-door dedup check then refuses a duplicate driver for X exactly as it does for a run-session request
And a command with no slug argument, such as "/next-integrate", stamps no working_slug
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
And a slug-bound lifecycle command stamps the create-session command's `working_slug` from the normalized args as creation-time metadata
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

<!-- planned-change:agent-usage-aware-dispatch -->

- **config** — the default-agent and per-agent enablement gate come from the configuration-resolved enabled-agent set. The thinking mode defaults to "slow" unless supplied by the caller.

<!-- change:agent-usage-aware-dispatch -->

- **config** — the configured default agent supplies the preferred agent when the request omits `agent`; per-agent enablement gates the candidate set before availability/degradation routing runs. The thinking mode defaults to "slow" unless supplied by the caller.

<!-- /planned-change:agent-usage-aware-dispatch -->

## Known caveats

- **Codex loader-message rewrite is asymmetric.** Only `/next-*` commands are rewritten for Codex; other slash commands sent to Codex pass through verbatim. The rewrite materializes the compiled prompt at `<commands-dir>/<cmd>.md` — if that file is missing on disk, Codex will fail at first read rather than at request time.
- **The full-command and the startup message diverge for Codex.** The full-command (used for the human-visible "initial input" echo) keeps the `/next-* <args>` form, while the startup message is the loader prompt. Don't infer one from the other, and don't derive lifecycle metadata from the rewritten startup message.

- **Claim-time session metadata repair is fallback only.** Both create doors — `/sessions/run` and the generic `POST /sessions` (New Session modal / `telec sessions start`) — stamp known slug-bound lifecycle metadata from the command argument at creation time. Workflow claim/adoption paths may backfill a missing `working_slug` later, but that repair does not replace creation-time stamping.

- **`detach=true` does NOT cancel polling on the spawned session** — it only suppresses listener registration for the caller. The spawned session still has its own output polling and adapter routing.
- **Invalid slash commands are not rejected.** A typo in `--command` (e.g., `/nxt-build`) passes validation as long as it starts with `/` — it simply launches a session that immediately fails inside the agent. Validation here is shape-only.

<!-- planned-change:agent-usage-aware-dispatch -->

- **Worker-lifecycle slug guard fires AFTER agent resolution.** A misconfigured-agent failure can mask a missing-slug error in the response; check the surface error code (slug-related vs. default-agent-related) to disambiguate.

<!-- change:agent-usage-aware-dispatch -->

- **Worker-lifecycle slug guard fires AFTER dispatch resolution.** A preferred-agent or no-agents-available failure can mask a missing-slug error in the response; check the surface error code (slug-related vs. dispatch-related) to disambiguate.

<!-- /planned-change:agent-usage-aware-dispatch -->

- **`subfolder` is not validated for traversal.** The entry trusts the caller; project-path joining and subdir sanitization happen downstream in the metadata-building path.
- **Dispatch privilege depends on role inference succeeding.** If the slash command isn't canonical (typo, custom command), no role is inferred and dispatch privilege is skipped — so ACL coverage assumes the slash command is canonical.

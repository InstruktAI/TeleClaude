---
description: 'Start a new agent session preloaded with a TeleClaude command as its first agent message (`telec sessions run`).'
visibility: 'public'
---

# Run Session With Command — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The run-session-with-command flow creates a brand-new agent session whose first agent input loads and runs a published entry procedure — not a free-form user message. The CLI verb `telec sessions run --command <procedure-id> --args ... --path ... --agent ... --mode ...` normalizes the request, resolves the procedure's declared role, parameters and dispatch defaults under `local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`, resolves the effective agent, composes the loader startup message that directs the agent to retrieve the procedure's instructions, sets the session title from the structured fields as `<role> <args>`, builds a typed launch intent that asks the agent_runtime service to start the agent and then deliver that message, and hands the request to session creation. The new session boots in its host pane with the resolved agent CLI; once the agent is ready, the loader message is delivered and polling begins. The loader is identical for every enabled runtime — no agent-specific rewrite exists. This is conceptually distinct from `sessions start` because the session is preloaded with an assignment: the very first thing the agent sees is the loader, not a human turn.

How the startup message reaches the agent depends on the agent CLI's own launch surface. An agent CLI that accepts an initial prompt as a launch argument receives the startup message that way — the message is part of the command that starts the agent, so the CLI consumes it when its own startup completes and there is no separate delivery step to time. An agent CLI with no such argument receives the startup message through prompt-state delivery once the readiness gate opens.

## Canonical fields

### Use cases

#### Agent resolution

```
Given a run-session request from a caller without a system role
And the request explicitly sets the "agent" field
When the agent_runtime service resolves the dispatch
Then it treats that field as a manual preference
And rejects unknown or disabled selected agents with a request-rejection error
```

```
Given a run-session request from a system-role caller
And the request explicitly sets the "agent" field
When the agent_runtime service resolves the dispatch
Then it treats that field as an automatic preferred candidate
And degraded or unavailable candidates fall through to the normal automatic order
And the response carries the selected agent and typed routing reason
```

```
Given a run-session request that omits the "agent" field
When the agent_runtime service resolves the dispatch
Then it treats the request as automatic preference
And uses the ordered agent list the entry procedure's dispatch declaration carries
And a prepare-orchestrator request additionally uses the todo kind to select its row
```

```
Given an automatic-preference run-session request has a preferred agent
And the preferred agent is unavailable or degraded
And another enabled agent is available for automatic dispatch
When the dispatch resolver runs
Then it selects the available fallback agent
And the response carries the selected agent
And one structured warning records the job role, preferred agent, selected agent,
and exact reason the preferred agent was not selected
```

```
Given an automatic-preference run-session request has a preferred agent
And no enabled agent is available for automatic dispatch
When the dispatch resolver runs
Then no session is created
And the response carries a structured no-agents-available error
```

```
Given a run-session request supplies an agent as a manual preference
And that agent is hard unavailable
And another enabled available agent exists
When the dispatch resolver runs
Then the request is rejected before session creation
And TeleClaude does not substitute the available agent
```

<!-- planned:adaptive-usage-routing -->

```
Given an automatic-preference run-session request has a preferred agent
And the preferred agent is enabled, available, and below quota-pressure thresholds
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
And one structured warning records quota pressure as the fallback reason
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
Then it preserves deterministic role order when quota comparison is unsupported
And it records diagnostic quota state without treating unknown quota as healthy
```

```
Given a run-session request supplies an available agent as a manual preference
And that agent is under quota pressure
When the dispatch resolver runs
Then it selects the supplied agent
And quota pressure does not reroute the manual preference
```

<!-- /planned:adaptive-usage-routing -->

#### UC-ARS1: Reviewer history and producer identity constrain no dispatch

```
Given an agent session asks to start a reviewer command for a target
And an earlier reviewer session or the producing session used one of the available agents
When TeleClaude chooses which agent runs the new session
Then those sessions' agents remain as eligible as if those sessions had never existed
And the accepted request reports the chosen agent and typed routing reason exactly as any automatic request with the same role context does
```

#### Command and arguments normalization

#### UC-CLR7: Normalization accepts a slash-prefixed procedure ID

```
Given a request with command "sdlc/procedure/lifecycle/work/build" and args "my-slug"
When the run-session preparation normalizes the inputs
Then a leading slash, when present, is stripped from the token
And the full command becomes "sdlc/procedure/lifecycle/work/build my-slug"
And the token is resolved against the published entry procedures, never against a command set
```

```
Given a request whose command carries a leading slash ("/sdlc/procedure/lifecycle/work/build")
When the request is validated
Then it is accepted and normalized to the procedure ID without the slash
And no request is rejected for lacking a leading slash
```

```
Given a request with an empty project
When the request is validated
Then it is rejected with "project required"
```

```
Given a request whose procedure declares a required `slug` parameter
And the args field is empty after trimming
When the run-session preparation validates the request
Then it is rejected naming the missing parameter
```

#### UC-CLR6: Startup-message assembly composes the runtime-identical loader

#### UC-CLR4: A dispatch names its procedure by domain-qualified snippet ID

```
Given a run-session request whose command is "sdlc/procedure/lifecycle/work/build"
When loader composition validates the name before any publication read
Then the ID is accepted as a canonical snippet identity
And the loader is composed for the published entry procedure that ID resolves to
```

#### UC-CLR5: Unsafe names compose no loader and read no file

```
Given a run-session request whose command contains traversal ("../x") or is not a well-formed snippet identity
When loader composition validates the name before any publication read
Then no loader is composed and no file is read
And the request is rejected naming the offending token
```

#### UC-CLR11: A declared dispatch whose procedure resolves to no published entry procedure is refused

```
Given a session launch that declares the procedure it dispatches
And that ID is safe but resolves to no published entry procedure — unknown, pending, not a procedure, or declaring no role
When loader composition runs
Then no session is created and the request is refused naming the unresolved procedure and the cause
And the refusal reaches an API caller as a 400
And no launch delivers the raw command text in place of the loader
```

#### UC-CLR1: Whether a procedure may run without arguments is its parameter declaration's decision

#### UC-CLR2: Empty arguments produce the loader message

#### UC-CLR3: A dispatched session's title reflects its record fields and is read by nothing

#### UC-CLR8: The session record carries the command the session was dispatched with

```
Given a run-session request whose command normalizes to a canonical name
When the session is created
Then the session record carries that normalized command alongside the system role, job, and working slug already derived from it
And a corpus-resident command that the command-role registry does not map still records its command, though it carries no job
And a session created without a dispatch command records no command
And any consumer needing to know which command a session runs reads it from the record
```

#### UC-CLR9: Sessions predating the recorded command are migrated forward from their titles

```
Given sessions exist whose records predate the recorded command
When the migration that introduces the field runs
Then every session whose title begins with a slash-prefixed token records that token, without the slash, as its command
And every other session records no command
And the count of migrated sessions equals the count of slash-titled sessions, so a partial migration fails rather than silently dropping sessions
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
Given a run-session request whose command is a worktree-bound worker lifecycle command (build, review-build, finalize)
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
Then the additional context is appended to BOTH the echoed full-command and the composed loader startup message under the literal header "ADDITIONAL CONTEXT:"
And every enabled runtime receives the identical extended message
```

#### UC-CLR10: A person starts a procedure with additional context

```
Given a person wants to start a published procedure with additional context
When they start it with that context
Then the new agent receives the context exactly once as additional context
And it remains separate from the procedure's declared inputs
```

#### UC-CLR12: An agent dispatches an entry procedure by its snippet ID and nothing shorter

```
Given an agent dispatches a session with the command sdlc/procedure/lifecycle/work/build
When the session starts
Then it loads that procedure and no other
And given the agent instead dispatches a retired command name such as sdlc/build or a bare token such as build
Then no session is started and the refusal names the unknown command
```

#### UC-CLR13: An orchestrator finds the session it dispatched by the command it dispatched

```
Given an orchestrator dispatched a session with a domain-qualified command for a slug
When the orchestrator later asks for the live session for that slug and command
Then it is given that session
And the session's recorded command carries the command exactly as dispatched
```

#### Dispatch privilege enforcement

```
Given the resolved procedure declares a target role of some class
And the calling identity carries a role of its own that is not full-reach
When the run-session preparation checks dispatch privilege
And the caller holds no dispatch grant for that class
Then it is rejected with "role '<caller>' cannot dispatch <procedure> (requires dispatch privilege for '<target role>')"
```

```
Given a caller carrying the integrator role
When it dispatches a focused-class procedure (e.g. the review-commits procedure for the commits it merged)
Then dispatch is permitted — the integrator holds `dispatch-focused` and is full-reach
And a full-reach caller is permitted every target class
```

#### UC-DPE4: Orchestrator may dispatch an integrator-role session

```
Given a caller carrying the orchestrator system role
When it dispatches the integrator-role command (/integrate), for example to clear a blocked repo-root sync
Then dispatch is permitted — the orchestrator's grant covers focused, orchestrator, and integrator roles
And the integrator's singleton lease still decides whether the new session drains or yields
```

#### UC-DPE1: A contained role with a dispatch grant starts only its granted class

```
Given a caller whose role is not full-reach and holds `dispatch-focused`
When it dispatches a focused-class procedure
Then dispatch is permitted
And when it dispatches a procedure declaring a role of another class
Then it is rejected naming the dispatch privilege it lacks
```

#### UC-DPE3: A task-lane session is full-reach

```
Given a caller carrying the task-runner role
When it dispatches an orchestrator procedure (the prepare or work overview)
Then dispatch is permitted — the task-lane roles are full-reach
And whether a second driver may bind the same todo remains the driver-start dedup's decision
```

#### UC-DPE5: The coordinator is full-reach

```
Given a caller carrying the coordinator role
When it dispatches any entry procedure
Then dispatch is permitted — the coordinator is full-reach
And what it does with that reach is its procedure's discipline, which drives no todo state machine
```

#### Lifecycle driver-start dedup

```
Given a todo slug X already driven by a live driver — a live orchestrator bound to X, or a live active-runner recorded for X
And an orchestrator-class create request that would bind X — a run-session request whose command carries the orchestrator system role ("prepare", "work", or a prepare drafting phase the orchestrator performs inline: "prepare-intake", "prepare-architecture", "prepare-plan") resolving to X, or a generic session-create on a "trees/X" worktree launching such a command
When the create-door dedup check runs before the session is created
Then the request is refused with a driver-start conflict that names the holder, returned as HTTP 409 detail
And no second session is created for X
And the refusal holds even when the requesting session is itself the holder — continuation in the holder's own lane happens in place via the operator door, never by creating a second orchestrator row
```

```
Given a todo slug X with a live active-runner recorded for X
And a task-lane create request that would bind X — a run-session or generic session-create launching "run-task" for X
When the create-door dedup check runs before the session is created
Then the request is refused with a driver-start conflict that names the holder, returned as HTTP 409 detail
And no second session is created for X
```

```
Given a todo slug X already driven by a live driver
And a producing worker child-spawn that would bind X — a run-session or generic session-create launching a command such as "build" or "review-build" for X
When the create-door dedup check runs
Then the request is allowed and the worker session is created sharing working_slug X, because an orchestrator and the producing workers it spawns legitimately share the slug
```

#### UC-DSD4: Every request for a held review subject is refused, with nothing a caller can say to admit a second

```
Given a live reviewer session holds review command C for todo slug X — C being one of "review-build", "review-plan", "review-architecture"
And an agent session asks to start that same command C for X
When TeleClaude decides whether the new session may be created
Then the request is refused with a driver-start conflict naming the holding session, surfaced to the caller as HTTP 409 detail
And no second reviewer session for C on X comes into being
And the refusal tells the caller how to address the holder instead
And no request the caller can compose admits a second live reviewer for C on X, so a caller that needs a different reviewer must first cause the holder to end
And a live reviewer holding a different review command on X does not refuse this one, because each review phase carries its own verdict
```

```
Given a todo slug X already driven by a live driver from a session other than the caller
And an operator work or prepare operation on X
When the operation's shared dedup check runs
Then the operation fails with a driver-start conflict whose completion-event error carries the holder, surfacing as an operator toast
And no second session is created for X
And the caller's own slug — when the caller is itself the holder — continues in place with no new session when the operation is for the lane the caller already drives
And an operation for the other lane is refused, because a session never changes lanes
```

An orchestrator-class create request for a todo created on this computer is
admitted under driver admission
(`local/projects/teleclaude/spec/feature/workflow/driver-admission`), which
decides whether the todo is held and orders concurrent starts. A request it
refuses for a holder returns HTTP 409 with the driver-start conflict naming the
holder. A request refused as busy returns HTTP 423 with a detail stating that
another start of the todo is in progress and naming the session it is starting.
Neither creates a session.

For a todo in a project on the GitHub workflow store, the driver-start conflict
also names the computer running the holding session, or the computers that did
not answer. A request whose admission cannot be decided — made on a computer
that is not the project's active computer, a project naming no active computer
or one whose active computer cannot be read, or no decision within the start
budget — returns HTTP 503 with a detail naming why, and creates no session.

#### UC-DSD3: A second commit reviewer for the same driver, project, and mode is refused

Commit review carries no todo slug — its subject is a commit series whose SHA set changes
every remediation round — so slug-keyed dedup cannot reach it. Its subject is identified
by the project, the driver that opened the review, and the thinking mode the review runs
at (`general/procedure/orchestration`). Starts at different modes are different subjects;
two starts at the same mode are one subject and dedup.

The driver is the caller's session when the caller is a session, and the authenticated
human when the caller is a terminal that carries no session. A session caller is keyed by
its session even when it also carries a human, so a session and its human's terminal are
two drivers. A caller that resolves to neither has no driver to key on and is refused: a
reviewer started without a key can never be found as a holder, so every later start
would be admitted beside it.

```
Given a live "review-commits" session for project P opened by initiator session I
And a create request launching "review-commits" for project P from the same initiator I
When the create-door dedup check runs
Then the request is refused with a driver-start conflict that names the holding reviewer session, returned as HTTP 409 detail
And no second reviewer session is created
And the refusal states the reuse command that addresses the holder instead
And the refusal does not depend on the requested SHAs, which differ every remediation round
```

#### UC-DSD5: A commit reviewer held by one driver or project admits another driver or project

```
Given a live "review-commits" session for project P opened by initiator session I
And a create request launching "review-commits" from a different initiator, or for a different project
When the create-door dedup check runs
Then the request is allowed, because independent drivers and separate projects review independent series
```

#### UC-DSD6: A closed commit reviewer holds nothing

```
Given every "review-commits" session for project P and initiator I is closed
And a create request launching "review-commits" for project P from initiator I
When the create-door dedup check runs
Then the request is allowed, because a closed reviewer holds nothing and the next series opens its own
```

#### UC-DSD7: A second commit reviewer for the same terminal human, project, and mode is refused

```
Given a live "review-commits" session for project P at mode M, started from a terminal authenticated as human H with no caller session
And a create request launching "review-commits" for project P at mode M from a terminal authenticated as H with no caller session
When the create-door dedup check runs
Then the request is refused with a driver-start conflict that names the holding reviewer session, returned as HTTP 409 detail
And no second reviewer session is created
And the refusal states the reuse command that addresses the holder instead
```

#### UC-DSD8: A commit reviewer held by a terminal human admits every other subject

```
Given a live "review-commits" session for project P at mode M, started from a terminal authenticated as human H
And a create request launching "review-commits" for project P at mode M from a terminal authenticated as a different human, or from a session whose human is H, or for a different project or mode
When the create-door dedup check runs
Then the request is allowed, because each of those is a different review subject
```

#### UC-DSD9: A commit reviewer a session opened never holds its human's terminal subject

```
Given a live "review-commits" session for project P at mode M, opened by initiator session I whose human is H
And a create request launching "review-commits" for project P at mode M from a terminal authenticated as H with no caller session
When the create-door dedup check runs
Then the request is allowed, because a reviewer a session opened never holds its human's terminal subject
```

#### UC-DSD10: A commit-review caller with no session and no authenticated human is refused

```
Given a create request launching "review-commits" whose caller carries neither a session nor an authenticated human
When the create-door dedup check runs
Then the request is refused as having no resolvable caller identity, returned as HTTP 409 detail
And no reviewer session is created
```

#### UC-DSD1: Held unclaimed lifecycle create requests are allowed but keep hold

```
Given a held todo slug X has no live holder
And an orchestrator-class create request would bind X through the New Session modal or `telec sessions run`
When the create-door dedup check runs before the session is created
Then the held flag alone does not refuse creation
And the create door does not clear hold
And hold release belongs to the lifecycle command's operator path after that path successfully claims or dispatches X
```

#### UC-DSD2: Generic create door stamps working_slug from a command argument

```
Given a generic session-create request through the New Session modal or `telec sessions start`
And its initial message is a slug-bound lifecycle command such as "work X" or "prepare X"
When the create-door preparation normalizes the request
Then the slug is inferred from the command's argument and stamped as the create-session command's `working_slug` at creation time — the same creation-time metadata `telec sessions run` produces
And this holds without a "trees/X" worktree subdir, so a repo-root manual start binds X
And the create-door dedup check then refuses a duplicate driver for X exactly as it does for a run-session request
And a command with no slug argument, such as "integrate", stamps no working_slug
```

#### Initiator binding

```
Given the caller identity has a session id
When the run-session preparation captures the initiator
Then the initiator session id is recorded and propagated as the spawning-session backlink on the new session
And email-bearing identities additionally produce a terminal-origin metadata stamp on the new session
```

#### Launch intent + session-creation handoff

```
Given the run-session preparation has produced a run plan
When the run flow dispatches the create flow
Then it builds a create-session command via the canonical command mapper

And the launch intent kind is "agent then message" carrying the effective agent, thinking mode, and the composed loader startup message
And the initial-input value is the bare "<command> <args>" string (for human-facing echo)

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

And the spawned session still runs the TeleClaude command normally

```

```
Given a request with detach=false (the default)
When the agent_runtime service creates the session
Then the listener-skip flag is false on the create-session command
And the caller's session is registered as a listener on the new session via the standard listener pipeline
And turn-complete output from the spawned session is forwarded back to the caller
```

#### Unknown command handling

```
Given a request whose command token does not match any known command value
When the run-session preparation parses the token
Then no command lookup succeeds
And no role inference happens (system role and job remain unset)
And dispatch privilege enforcement is skipped
And a token that resolves to an installed command document is still launched with that document's loader, carrying no role
And a token that resolves to no installed command document is refused rather than launched
```

#### UC-RSC-LP1: A launch-argument agent receives the startup message as part of its start command

```
Given a run-session request whose resolved agent CLI accepts an initial prompt as a launch argument
When the agent_runtime service executes the start-agent-then-deliver launch intent
Then the startup message is passed to the agent start command as its initial-prompt argument
And no prompt-state delivery is attempted for that startup message
```

#### UC-RSC-RG1: Pre-render stillness does not establish startup readiness

```gherkin
Given an orchestration agent starts a session whose initial message is delivered after launch
And the launched agent has not rendered its interactive surface or reported that it started
When the host pane remains unchanged before that first render
Then the startup readiness gate stays closed
And TeleClaude does not deliver the initial message into the pre-start terminal state
```

#### UC-RSC-RG2: Startup readiness does not author agent status

```gherkin
Given an orchestration agent starts a session whose initial message is delivered after launch
And host-pane readiness permits delivery before the launched agent reports that it started
When TeleClaude delivers the initial message
Then the session does not appear active on the strength of host-pane readiness
And the session appears active only after the launched agent reports that it started
```

#### UC-RSC-RG3: Fresh post-launch initial input preserves composer protection

```gherkin
Given an orchestration agent starts a fresh session whose initial message is delivered after launch
And the runtime's startup gate has opened
When the platform delivers the accepted initial message
Then it applies the same complete-composer observation as existing-session text delivery
And it submits only when that composer is empty
And an occupied composer retains its existing text with the platform message appended without submission
And a menu or ambiguous screen is left unchanged
```

### Cross-context references

- **workflow** — commands resolved here correspond to workflow lifecycle verbs (`build`, `review-build`, `finalize`) listed in the worker-lifecycle command set. Workflow owns the slug semantics and the command documents the composed loader reads.

- **identity** — the caller identity (email, system role, session id) gates the run; the run-session clearance is the auth dependency. Email-bearing identities produce terminal-origin metadata; terminal/agent identities form the initiator-session backlink. Dispatch privilege is an identity-domain ACL.

- **context** — the command corpus lives in the context bounded context. agent_runtime validates the run-session command token shape, routes the new-session dispatch, and composes the command loader message; it does not interpret command semantics.

- **config** — per-agent enablement gates the command-ordered candidate set before availability/degradation routing runs. An omitted agent is automatic preference; recognized commands use their command-matrix row and generic session creation uses the Claude-first global order. Fresh-session thinking mode follows the same command matrix: explicit caller mode wins, command defaults are explicit, and an unrecognized command without an explicit mode is rejected. `review-commits` defaults to `slow`; a commit review whose scope resolves to `med` under `general/procedure/orchestration` supplies it explicitly.

## Known caveats

- **Command loader-message assembly is uniform.** Every enabled runtime receives the same loader; no agent-specific rewrite path exists, so no behavior difference can hide in one runtime.
- **The full-command and the startup message diverge for every supported agent.** The full-command (used for the human-visible "initial input" echo) carries the bare `<command> <args>` form, while the startup message is the loader prompt. Don't infer one from the other, and don't derive lifecycle metadata from the loader startup message.

- **Claim-time session metadata repair is fallback only.** Both create doors — `/sessions/run` and the generic `POST /sessions` (New Session modal / `telec sessions start`) — stamp known slug-bound lifecycle metadata from the command argument at creation time. Workflow claim/adoption paths may backfill a missing `working_slug` later, but that repair does not replace creation-time stamping.

- **`detach=true` does NOT cancel polling on the spawned session** — it only suppresses listener registration for the caller. The spawned session still has its own output polling and adapter routing.

- **Unknown command names are not rejected.** A typo in `--command` (e.g., `nxt-build`) passes validation — it simply launches a session that immediately fails inside the agent. Validation here is shape-only, and the shape no longer includes required punctuation: a bare command name is the expected form, and a leading slash is tolerated for compatibility rather than demanded.

- **Worker-lifecycle slug guard fires AFTER dispatch resolution.** A preferred-agent or no-agents-available failure can mask a missing-slug error in the response; check the surface error code (slug-related vs. dispatch-related) to disambiguate.

- **`subfolder` is not validated for traversal.** The entry trusts the caller; project-path joining and subdir sanitization happen downstream in the metadata-building path.

- **Dispatch privilege depends on role inference succeeding.** If the command isn't canonical (typo, unknown name), no role is inferred and dispatch privilege is skipped — so ACL coverage assumes the command is canonical.

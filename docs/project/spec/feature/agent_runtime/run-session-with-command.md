---
id: 'project/spec/feature/agent_runtime/run-session-with-command'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Start a new agent session preloaded with a slash command as its first agent message (POST /sessions/run; `telec sessions run`).'
---

# Run Session With Command — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The `run-session-with-command` flow creates a brand-new agent session whose first agent input is a slash command — not a free-form user message. The daemon's `POST /sessions/run` endpoint (CLI: `telec sessions run --command /<cmd> --args ... --project ... --agent ... --mode ...`) normalizes the request, resolves the effective agent, optionally rewrites the startup message for Codex, builds a typed `SessionLaunchIntent` of kind `AGENT_THEN_MESSAGE`, and hands it to `CommandService.create_session`. The new session boots in tmux with the resolved agent CLI; once the agent is ready, the daemon delivers the rewritten startup message and polling begins. This is conceptually distinct from `sessions start` because the session is _preloaded_ with a slash-command invocation — the very first thing the agent sees is the command, not a human turn.

## Canonical fields

### Behavioral contract

#### Agent resolution

```
Given a POST /sessions/run request
When the request explicitly sets the "agent" field
Then the daemon validates the requested agent against the enabled-agent set via assert_agent_enabled
And rejects unknown or disabled agents with HTTP 400
```

```
Given a POST /sessions/run request that omits the "agent" field
When the daemon resolves the effective agent
Then it calls get_default_agent() to obtain the project/system default
And rejects with HTTP 409 when no default agent is configured
```

#### Command and arguments normalization

```
Given a request with command="/next-build" and args="my-slug"
When _prepare_run_session normalizes the inputs
Then leading slashes are stripped from the command token
And the full command becomes "/next-build my-slug"
And the slash command is parsed against the SlashCommand enum for role inference
```

```
Given a request whose command does not start with "/"
When run_session validates the request
Then it rejects with HTTP 400 "command must start with '/'"
```

```
Given a request with empty project
When run_session validates the request
Then it rejects with HTTP 400 "project required"
```

```
Given a request whose normalized command is in WORKER_LIFECYCLE_COMMANDS (next-build, next-review-build, next-fix-review, next-finalize)
And the args field is empty after trimming
When _prepare_run_session validates the request
Then it rejects with HTTP 400 "/<command> requires a slug argument"
```

#### Codex loader-message rewrite

```
Given effective_agent is "codex"
And the normalized command starts with "next-" (e.g. "/next-build my-slug")
When _rewrite_codex_next_startup_message processes the startup message
Then the startup message is replaced by a Codex loader prompt that
  instructs Codex to read the compiled command prompt file at
  COMMANDS_DIR / "<command>.md" and treat the args as inputs to that
  instruction set
And the public full_command (used for the human-visible initial_input echo) remains the original "/<command> <args>" form
```

```
Given effective_agent is "codex"
And the normalized command starts with "/next-"
And the args field is empty
When _rewrite_codex_next_startup_message validates the inputs
Then it rejects with HTTP 400 "/<command> requires a slug argument"
```

```
Given effective_agent is not "codex"
When _rewrite_codex_next_startup_message processes the startup message
Then the startup message is returned unchanged
```

#### Subfolder routing

```
Given a request with subfolder="services/api"
When run_session builds the session metadata
Then _build_metadata receives subdir="services/api"
And the new session's working directory is anchored to <project>/services/api
And an empty/missing subfolder leaves subdir as None
```

#### Additional context propagation

```
Given a request with additional_context="<some preamble>"
When _prepare_run_session assembles the launch payload
Then the additional context is appended to BOTH the echoed full_command and the startup message under the literal header "ADDITIONAL CONTEXT:"
And both Codex (post-loader-rewrite) and non-Codex agents receive the extended message
```

#### Dispatch privilege enforcement

```
Given the resolved slash command maps to a target system role in COMMAND_ROLE_MAP
And the calling identity carries a system_role of its own
When _prepare_run_session checks DISPATCH_ALLOWED[identity.system_role]
And the target role is NOT in that allowed set
Then it rejects with HTTP 403 "role '<caller>' cannot dispatch /<command> (requires dispatch privilege for '<target>')"
```

#### Initiator binding

```
Given the caller identity has a session_id that does not start with "web:"
When _prepare_run_session captures the initiator
Then initiator_session_id is set to identity.session_id and propagated as the spawning-session backlink on the new session
And web-origin callers (session_id prefixed "web:") do not establish an initiator link
And email-bearing identities additionally produce a WebOriginMetadata stamp on the new session
```

#### Launch intent + create_session handoff

```
Given _prepare_run_session has produced a RunSessionPlan
When run_session dispatches the create flow
Then it builds a CreateSessionCommand via CommandMapper.map_api_input("new_session", ...)
And metadata.launch_intent is a SessionLaunchIntent of kind AGENT_THEN_MESSAGE carrying the effective_agent, thinking_mode, and (rewritten) startup message
And initial_input is the original "/<command> <args>" string (for human-facing echo)
And skip_listener_registration mirrors request.detach
And on success the response carries session_id, tmux_session_name, and the resolved agent
```

#### Detached vs attached behavior

```
Given a request with detach=true
When the daemon creates the session
Then skip_listener_registration is true on the CreateSessionCommand
And the caller's session is NOT registered as a listener on the new session
And the caller will NOT receive output forwarding from the spawned session
And the spawned session still runs the slash command normally
```

```
Given a request with detach=false (the default)
When the daemon creates the session
Then skip_listener_registration is false on the CreateSessionCommand
And the caller's session is registered as a listener on the new session via the standard listener pipeline
And turn-complete output from the spawned session is forwarded back to the caller
```

#### Invalid slash command handling

```
Given a request whose command token does not match any SlashCommand enum value
When _prepare_run_session parses the token
Then slash_cmd is None
And no role inference happens (system_role and job remain None)
And dispatch privilege enforcement is skipped
And the command is still launched verbatim into the agent — agent-side handling decides whether the command is meaningful
```

### Implementation pointers (v1)

- `teleclaude/api/sessions_actions_routes.py:621` — `run_session` (route handler, request validation, command-service dispatch).
- `teleclaude/api/sessions_actions_routes.py:316` — `_prepare_run_session` (normalization, role-info, dispatch privilege check, RunSessionPlan assembly).
- `teleclaude/api/sessions_actions_routes.py:276` — `_resolve_run_session_agent` (explicit agent vs default, enabled-set check).
- `teleclaude/api/sessions_actions_routes.py:289` — `_build_codex_loader_message` (compiled prompt loader template).
- `teleclaude/api/sessions_actions_routes.py:299` — `_rewrite_codex_next_startup_message` (Codex `/next-*` rewrite quirk).
- `teleclaude/api/sessions_actions_routes.py:72` — `WORKER_LIFECYCLE_COMMANDS` set (slug-required guard).
- `teleclaude/api_models.py:725` — `RunSessionRequest` Pydantic shape (defaults: agent=claude, thinking_mode=slow, detach=false, subfolder="", additional_context="").
- `teleclaude/core/command_service.py` — `COMMAND_ROLE_MAP`, `DISPATCH_ALLOWED` (role inference and dispatch ACL tables).
- `teleclaude/paths.py` — `COMMANDS_DIR` (Codex loader prompt root).

### Cross-context references

- **workflow** — slash commands resolved here correspond to workflow lifecycle verbs (`/next-build`, `/next-review-build`, `/next-fix-review`, `/next-finalize`) listed in `WORKER_LIFECYCLE_COMMANDS`. Workflow owns the slug semantics and the command-prompt artifacts that Codex's loader reads.
- **identity** — caller `CallerIdentity` (email, system_role, session_id) gates the run; `clearance_sessions_run` is the auth dependency. Web-origin identities produce `WebOriginMetadata`; terminal/agent identities form the `initiator_session_id` backlink. `DISPATCH_ALLOWED` is an identity-domain ACL.
- **context** — the slash command resolution surface (command + skill discovery) lives in the context bounded context. agent_runtime only validates the token shape and routes; it does not interpret command semantics.
- **config** — `get_default_agent()` and `assert_agent_enabled(...)` come from the config-resolved enabled-agent set. `thinking_mode` defaults to the request model's `"slow"` value unless supplied by the caller.

## Known caveats

- **Codex loader-message rewrite is asymmetric.** Only `/next-*` commands are rewritten for Codex; other slash commands sent to Codex pass through verbatim. The rewrite materializes the compiled prompt at `COMMANDS_DIR / "<cmd>.md"` — if that file is missing on disk, Codex will fail at first read rather than at request time.
- **The `full_command` and the `startup_message` diverge for Codex.** `full_command` (used for the human-visible "initial_input" echo) keeps the `/next-* <args>` form, while `startup_message` is the loader prompt. Don't infer one from the other.
- **`detach=true` does NOT cancel polling on the spawned session** — it only suppresses listener registration for the caller. The spawned session still has its own output poller and adapter routing.
- **Invalid slash commands are not rejected.** A typo in `--command` (e.g. `/nxt-build`) passes validation as long as it starts with `/` — it simply launches a session that immediately fails inside the agent. Validation here is shape-only.
- **WORKER_LIFECYCLE_COMMANDS slug guard fires AFTER agent resolution.** A misconfigured-agent failure can mask a missing-slug error in the response; check the HTTP status (400 for slug, 409 for default agent) to disambiguate.
- **`subfolder` is not validated for traversal.** The endpoint trusts the caller; project-path joining and subdir sanitization happen downstream in `_build_metadata` / `split_project_path_and_subdir`.
- **Dispatch privilege depends on role inference succeeding.** If the slash command isn't in `SlashCommand` (typo, custom command), no role is inferred and `DISPATCH_ALLOWED` is skipped — so ACL coverage assumes the slash command is canonical.

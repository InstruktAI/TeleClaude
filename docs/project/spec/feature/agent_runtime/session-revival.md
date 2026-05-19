---
id: 'project/spec/feature/agent_runtime/session-revival'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Revive an ended or unbound agent session by binding the prior native transcript chain to a fresh agent process so context resumes intact.'
---

# Session Revival — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Session revival brings an ended, closed, or externally-started agent conversation back to life inside the TeleClaude session ledger. Two entry shapes route through the same `POST /sessions/{session_id}/revive` endpoint: the **TeleClaude form**, where the path id names an existing session row and revival reuses it; and the **native form** (`--agent <name>`), where the path id is the agent CLI's own native session id (Claude `.jsonl`, Gemini `.jsonl`, Codex `.toml`) and the daemon either adopts an existing TeleClaude session that already references that native id or creates a new TeleClaude session bound to it.

Once a TeleClaude `session_id` is resolved, revival delegates to the same `restart_agent` command-handler used by agent restart: the tmux session is (re)adopted, the agent process is launched with `--resume <native_session_id>`, and the agent CLI itself replays its full transcript on startup so the resumed agent sees its original context intact. Revival is the verb that crosses session boundaries (new ledger row possible, agent process is always fresh); restart is the verb that stays inside one session row.

## Canonical fields

### Behavioral contract

#### TeleClaude session id form (no `--agent`)

```
Given a caller invokes `telec sessions revive <session_id>` without `--agent`
And `<session_id>` matches a row in agent_runtime.sessions
When the daemon handles POST /sessions/{session_id}/revive
Then the existing session row is reused
And the daemon validates the row has an active_agent and a native_session_id
And the daemon delegates to restart_agent, which resumes the agent with --resume <native_session_id>
And the response carries the same session_id and the (possibly newly adopted) tmux_session_name
```

```
Given a caller invokes revive without `--agent`
And the session row has no active_agent
When the daemon handles the request
Then the daemon rejects with HTTP 409 "No active agent for this session"
And no agent process is started
```

```
Given a caller invokes revive without `--agent`
And the session row has no native_session_id
When the daemon handles the request
Then the daemon rejects with HTTP 409 "No native session ID - start agent first"
And no agent process is started
```

#### Native form (`--agent <name>`) with existing TeleClaude binding

```
Given a caller invokes `telec sessions revive <native_id> --agent claude`
And a row in agent_runtime.sessions already has native_session_id = <native_id>
And that row's active_agent equals "claude"
When the daemon resolves the revive request
Then the daemon reuses that row's session_id
And revival proceeds as in the TeleClaude form
```

```
Given a caller invokes revive with `--agent claude`
And a row already bound to <native_id> has active_agent != "claude"
When the daemon resolves the revive request
Then the daemon rejects with HTTP 409 ("Native session belongs to agent '<other>', not 'claude'")
And no new session is created
```

#### Native form with no existing TeleClaude binding (fresh adoption)

```
Given a caller invokes `telec sessions revive <native_id> --agent <name>`
And no row in agent_runtime.sessions references <native_id>
When the daemon resolves the revive request
Then the daemon validates that <native_id> resolves to a transcript on disk for that agent
And on success, the daemon mints a fresh TeleClaude session_id (UUID4)
And creates a new session row with native_session_id = <native_id>, headless = true, launch_intent.kind = AGENT, launch_intent.native_session_id = <native_id>
And associates the row with the caller's identity (initiator_session_id, email, origin = TERMINAL)
And, if `?project=<path>` was provided, splits it against trusted_dirs and stores project_path and subdir on the row
And then proceeds with restart_agent against the newly minted session_id
```

```
Given a caller invokes revive with `--agent <name>`
And <native_id> does NOT resolve to a transcript on disk for that agent
When the daemon attempts to validate the native id
Then the daemon rejects with HTTP 404 "Native session ID is not valid for agent '<name>'"
And no session row is created
```

```
Given a caller invokes revive with `--agent <unknown>`
And `<unknown>` is not a value of AgentName
When the daemon attempts to validate the native id
Then AgentName.from_str raises ValueError, _native_session_exists_for_agent returns False
And the daemon rejects with HTTP 404 (per the validation-failure path)
```

#### Per-agent transcript resolution

```
Given the revival validates a native id for a Codex agent
When the daemon checks transcript existence
Then it calls discover_codex_transcript_path(<native_id>) and treats a non-None result as proof of existence
```

```
Given the revival validates a native id for Claude or Gemini
When the daemon checks transcript existence
Then it iterates discover_transcripts([agent_name]) and matches on extract_session_id(path, agent_name) == <native_id>
And returns True on first hit, False if no transcript matches
```

#### Restart leg of revival

```
Given a TeleClaude session_id has been resolved (reused or freshly created)
When the daemon hands off to restart_agent
Then the agent CLI is launched with `--resume <native_session_id>` (the agent CLI replays its own transcript)
And if the session was closed (closed_at set), revival clears closed_at and sets lifecycle_status = headless before launch
And if no tmux session exists for the row, the daemon adopts a fresh tmux session in headless mode before launch
And the response payload is `{status: success, session_id, tmux_session_name, agent}` (CreateSessionResponseDTO)
```

### Implementation pointers (v1)

- HTTP route: `teleclaude/api/sessions_actions_routes.py:495` (`revive_session`)
- TeleClaude vs native id resolution: `teleclaude/api/sessions_actions_routes.py:139` (`_resolve_revive_session_id`)
- Native-id existence probe: `teleclaude/api/sessions_actions_routes.py:95` (`_native_session_exists_for_agent`)
- Per-agent transcript discovery: `teleclaude/core/codex_transcript.py` (`discover_codex_transcript_path`), `teleclaude/utils/transcript_discovery.py` (`discover_transcripts`, `extract_session_id`)
- Session minting on fresh native adoption: `teleclaude/api/sessions_actions_routes.py:174` (`CreateSessionCommand`)
- Restart leg shared with agent restart: `teleclaude/core/command_handlers/_agent.py:311` (`agent_restart`)
- CLI verb: `teleclaude/cli/telec/handlers/misc.py:115` (`_handle_revive`, `_revive_session`)
- Clearance dependency: `clearance_sessions_revive` in `teleclaude/api/auth.py`

### Cross-context references

- **identity** — `clearance_sessions_revive` resolves the `CallerIdentity` (session token + role); the caller's `session_id`, `email`, and origin metadata are stamped onto any freshly-minted session row as `initiator_session_id` and `TerminalOriginMetadata`.
- **config** — `assert_agent_enabled` (invoked transitively by `restart_agent`) checks per-agent enablement against `config.computer`; `config.computer.get_all_trusted_dirs()` gates the `?project=...` query-param split so revival cannot drop a session into an arbitrary directory.
- **session_mirrors** — revival via the native form creates a new TeleClaude `session_id`, but the `native_session_id` is the join key the mirror layer uses to thread transcript continuity; mirror processing therefore sees both the prior and the new session rows as records sharing one native chain.

## Known caveats

- **Native-form revival without an existing binding always mints a new session row.** There is no "promote this orphan native id back into the original TeleClaude session" path — if the original row was deleted or was never created, revival creates a new row with a new `session_id`.
- **The transcript continuity is the agent CLI's own.** TeleClaude does not splice transcript files; resumption relies on the agent CLI's `--resume <native_session_id>` semantics. For Codex this maps to a `.toml` file path; for Claude/Gemini it maps to a `.jsonl` path indexed by directory layout.
- **Agent mismatch on an existing native binding is rejected, not switched.** If a native id was first launched as Claude and a revive request asks for Gemini against the same id, the daemon returns 409 rather than relaunch the transcript under a different agent.
- **Revival on an open running session has the same effect as restart.** Reviving a row whose agent is still alive will SIGTERM the agent process and relaunch it; the verb is named for the typical case (closed/ended) but the implementation path is symmetric.
- **`--attach` is a client-side affordance only.** The daemon never attaches the caller's terminal to tmux; the CLI handler attaches locally after a successful revive response.
- **No completion-event guarantees on the HTTP response.** Unlike `agent_restart`, `revive_session` awaits `restart_agent` synchronously and returns when the relaunch has been dispatched; agent readiness is observed downstream (e.g., via `AGENT_READY` events on the bus), not in the HTTP response.

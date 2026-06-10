---
description: 'Revive an ended or unbound agent session by binding the prior native transcript chain to a fresh agent process so context resumes intact.'
visibility: 'public'
---

# Session Revival — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Session revival brings an ended, closed, or externally-started agent conversation back to life inside the TeleClaude session ledger. Two entry shapes route through the same revive-session flow: the **TeleClaude form**, where the supplied identifier names an existing session row and revival reuses it; and the **native form** (`--agent <name>`), where the supplied identifier is the agent CLI's own native session id (Claude transcript, Gemini transcript, Codex rollout) and the agent_runtime service either adopts an existing TeleClaude session that already references that native id or creates a new TeleClaude session bound to it.

Once a TeleClaude session id is resolved, revival delegates to the same restart-agent flow used by agent restart: the host pane is (re)adopted, the agent process is launched with resume-from-transcript semantics, and the agent CLI itself replays its full transcript on startup so the resumed agent sees its original context intact. Revival is the verb that crosses session boundaries (new ledger row possible, agent process is always fresh); restart is the verb that stays inside one session row.

## Canonical fields

### Use cases

#### TeleClaude session id form (no `--agent`)

```
Given a caller invokes `telec sessions revive <session_id>` without `--agent`
And `<session_id>` matches a row in the agent_runtime session ledger
When the agent_runtime service handles the revive request
Then the existing session row is reused
And the service validates the row has an active agent and a native session id
And the service delegates to the restart-agent flow, which resumes the agent from its transcript
And the response carries the same session id and the (possibly newly adopted) host-pane reference
```

```
Given a caller invokes revive without `--agent`
And the session row has no active agent
When the service handles the request
Then it is rejected with "No active agent for this session"
And no agent process is started
```

```
Given a caller invokes revive without `--agent`
And the session row has no native session id
When the service handles the request
Then it is rejected with "No native session ID - start agent first"
And no agent process is started
```

#### Native form (`--agent <name>`) with existing TeleClaude binding

```
Given a caller invokes `telec sessions revive <native_id> --agent claude`
And a row in the session ledger already has native_session_id = <native_id>
And that row's active agent equals "claude"
When the service resolves the revive request
Then the service reuses that row's session id
And revival proceeds as in the TeleClaude form
```

```
Given a caller invokes revive with `--agent claude`
And a row already bound to <native_id> has an active agent other than "claude"
When the service resolves the revive request
Then it is rejected with "Native session belongs to agent '<other>', not 'claude'"
And no new session is created
```

#### Native form with no existing TeleClaude binding (fresh adoption)

```
Given a caller invokes `telec sessions revive <native_id> --agent <name>`
And no row in the session ledger references <native_id>
When the service resolves the revive request
Then the service validates that <native_id> resolves to a transcript on disk for that agent
And on success, the service mints a fresh TeleClaude session id (UUID4)
And creates a new session row with native_session_id = <native_id>, headless = true, launch intent kind = AGENT, launch intent native_session_id = <native_id>
And associates the row with the caller's identity (initiator session id, email, origin = TERMINAL)
And, if a project path was provided, splits it against trusted directories and stores project path and subdir on the row
And then proceeds with the restart-agent flow against the newly minted session id
```

```
Given a caller invokes revive with `--agent <name>`
And <native_id> does NOT resolve to a transcript on disk for that agent
When the service attempts to validate the native id
Then it is rejected with "Native session ID is not valid for agent '<name>'"
And no session row is created
```

```
Given a caller invokes revive with `--agent <unknown>`
And `<unknown>` is not a recognized agent name
When the service attempts to validate the native id
Then the agent-name resolution fails and the native-session existence check returns false
And the request is rejected per the validation-failure path
```

#### Per-agent transcript resolution

```
Given the revival validates a native id for a Codex agent
When the service checks transcript existence
Then it consults the Codex transcript discovery helper and treats a non-empty result as proof of existence
```

```
Given the revival validates a native id for Claude or Gemini
When the service checks transcript existence
Then it iterates discovered transcripts for that agent and matches by extracted native id
And returns true on first hit, false if no transcript matches
```

#### Restart leg of revival

```
Given a TeleClaude session id has been resolved (reused or freshly created)
When the service hands off to the restart-agent flow
Then the agent CLI is launched with resume-from-transcript semantics (the agent CLI replays its own transcript)
And if the session was closed (closed-at marker set), revival clears the marker and sets lifecycle status to headless before launch
And if no host pane exists for the row, the service adopts a fresh host pane in headless mode before launch
And the response payload reports a successful create with session id, host-pane reference, and agent
```

### Cross-context references

- **identity** — the revive clearance resolves the caller identity (session token + role); the caller's session id, email, and origin metadata are stamped onto any freshly-minted session row as initiator session id and terminal-origin metadata.
- **config** — per-agent enablement (invoked transitively by the restart-agent flow) is checked against configuration; trusted-directory configuration gates the project-path argument so revival cannot drop a session into an arbitrary directory.
- **session_mirrors** — revival via the native form creates a new TeleClaude session id, but the native session id is the join key the mirror layer uses to thread transcript continuity; mirror processing therefore sees both the prior and the new session rows as records sharing one native chain.

## Known caveats

- **Native-form revival without an existing binding always mints a new session row.** There is no "promote this orphan native id back into the original TeleClaude session" path — if the original row was deleted or was never created, revival creates a new row with a new session id.
- **The transcript continuity is the agent CLI's own.** TeleClaude does not splice transcript files; resumption relies on the agent CLI's native resume semantics. For Codex this maps to a rollout-file path; for Claude/Gemini it maps to transcript files indexed by directory layout.
- **Agent mismatch on an existing native binding is rejected, not switched.** If a native id was first launched as Claude and a revive request asks for Gemini against the same id, the service rejects rather than relaunch the transcript under a different agent.
- **Revival on an open running session has the same effect as restart.** Reviving a row whose agent is still alive will terminate the agent process and relaunch it; the verb is named for the typical case (closed/ended) but the underlying path is symmetric.
- **`--attach` is a client-side affordance only.** The agent_runtime service never attaches the caller's terminal to a host pane; the CLI handler attaches locally after a successful revive response.
- **No completion-event guarantees on the response.** Unlike agent restart, revive awaits the restart-agent flow synchronously and returns when the relaunch has been dispatched; agent readiness is observed downstream (e.g., via the session-ready signal on the event bus), not in the response.

---
description: Revive an ended or unbound agent session by binding the prior native
  transcript chain to a fresh agent process so context resumes intact.
visibility: public
---

# Session Revival — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

Session revival brings an ended, closed, or externally-started agent conversation back to life inside the TeleClaude session ledger. Two entry shapes route through the same revive-session flow: the **TeleClaude form**, where the supplied identifier names an existing session row and revival reuses it; and the **native form** (`--agent <name>`), where the supplied identifier is the agent CLI's own native session id (Claude transcript, Gemini transcript, Codex rollout) and the agent_runtime service either adopts an existing TeleClaude session that already references that native id or creates a new TeleClaude session bound to it.

Once a TeleClaude session id is resolved, revival delegates to the same restart-agent flow used by agent restart: the host pane is (re)adopted, the agent process is launched with resume-from-transcript semantics, and the agent CLI itself replays its full transcript on startup so the resumed agent sees its original context intact. Revival is the verb that crosses session boundaries (new ledger row possible, agent process is always fresh); restart is the verb that stays inside one session row.

## Canonical fields

### Use cases

#### UC-SR1: Fresh adoption recovers the recorded project from the originating prior row

#### UC-SR2: Fresh adoption with no prior row recovers the project from the Claude transcript

#### UC-SR3: Fresh adoption recovers the project from a Codex rollout's session metadata

#### UC-SR4: Fresh adoption confirms a Gemini legacy project by hash

#### UC-SR5: A caller can diagnose why a conversation cannot be revived

```
Scenario: A TeleClaude session cannot be resumed
  Given a caller names a TeleClaude session that is missing, has no active agent, or has no native transcript binding
  When they request revival
  Then the request is refused with the unavailable condition identified
  And no agent process is started

Scenario: A native conversation cannot be adopted
  Given a caller names an unknown agent, an invalid native transcript, a transcript bound to another agent, or a project that cannot be recovered
  When they request revival
  Then the request is refused with the condition and any required next step identified
  And no session is created in the caller's current directory as a substitute
```

#### UC-SR6: Fresh adoption recovers the session title from the originating prior row

#### UC-SR9: A caller can resume a conversation by its session or native identity

```gherkin
Scenario: Resume by TeleClaude session id
  Given a caller wants to resume a conversation with an existing TeleClaude session id
  When they revive that session
  Then the same TeleClaude session continues from its native transcript
  And the response identifies the resumed session after launch is dispatched

Scenario: Resume a native id already bound to a TeleClaude session
  Given a caller wants to resume a native session that is already bound to the matching agent
  When they revive it by its native id
  Then the existing TeleClaude session continues from that transcript

Scenario: Adopt an unbound native conversation
  Given a caller wants to resume a valid native conversation with no live TeleClaude session
  When they revive it with the matching agent
  Then a TeleClaude session continues from that transcript in its originating project
  And any title retained for the conversation remains recognizable
  And the response returns the new session id after launch is dispatched, without claiming readiness
```

#### UC-SR10: A revived agent keeps its status until it acts

```gherkin
Given a session was closed with a recorded agent activity state
When the session is revived
Then its recorded activity state, reason and entry time are preserved
And revival itself supplies no input and creates no new startup observation window
And a newly adopted conversation remains unknown until its first native activity signal
And any outstanding silence observation remains governed by its owning run or turn and current supervising caller
And the revival does not turn elapsed silence into a failure verdict
```

#### UC-SR7 — Revival preserves generation and delivery identity across native-session replacement

#### UC-SR8: A caller can continue a revived conversation

```gherkin
Given a caller has revived a conversation and the resumed agent is ready for input
When the caller sends its first continuation through the platform
Then the continuation is submitted exactly once to the resumed agent
And the agent receives it in the restored conversation
```

### Cross-context references

- **supervisory silence** — `local/projects/teleclaude/spec/feature/agent_runtime/supervisory-silence-observations` owns caller-only missing-signal observations and their assessment boundary.

- **identity** — the client clears the revive before sending it (`feature/identity/command-clearance`) and the request carries the caller it resolved; the caller's session id, email, and origin metadata are stamped onto any freshly-minted session row as initiator session id and terminal-origin metadata.
- **config** — per-agent enablement (invoked transitively by the restart-agent flow) is checked against configuration; the project registry's entries (`local/projects/teleclaude/spec/feature/config/project-registry`) are what a recovered working directory is split against.
- **session_mirrors** — revival via the native form creates a new TeleClaude session id, but the native session id is the join key the mirror layer uses to thread transcript continuity; mirror processing therefore sees both the prior and the new session rows as records sharing one native chain.
- **session input and output** — generation and delivery state stays qualified by runtime, native identity, and native position under `local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`; revival changes no cursor or generation ownership.

## Known caveats

- **Native-form revival without an existing binding always mints a new session row.** There is no "promote this orphan native id back into the original TeleClaude session" path — if the original row was deleted or was never created, revival creates a new row with a new session id.

- **A freshly-minted revival row recovers the native session's project from the most authoritative source available.** Resolution runs in order: the earliest prior session row bound to <native_id> (a fast path that survives session closure), then the project the native transcript itself records (the transcript directory and its embedded working directory for Claude, the session-metadata working directory for Codex, the hash-identified project for Gemini), then — only for Gemini legacy storage keyed by a project-path hash — the caller's invocation directory when its hash matches the transcript's project hash. When none of those resolve, revival rejects with a clear error rather than silently rooting the session at the caller's invocation directory. The earliest prior row wins over later ones, so a project recorded by an earlier buggy revive cannot override the original recording.

- **The transcript continuity is the agent CLI's own.** TeleClaude does not splice transcript files; resumption relies on the agent CLI's native resume semantics. For Codex this maps to a rollout-file path; for Claude/Gemini it maps to transcript files indexed by directory layout.
- **Agent mismatch on an existing native binding is rejected, not switched.** If a native id was first launched as Claude and a revive request asks for Gemini against the same id, the service rejects rather than relaunch the transcript under a different agent.

- **Revival on an open running session has the same effect as restart.** Reviving a row whose agent is still alive will terminate the agent process and relaunch it; the verb is named for the typical case (closed/ended) but the underlying path is symmetric.

- **`--attach` is a client-side affordance only.** The agent_runtime service never attaches the caller's terminal to a host pane; the CLI handler attaches locally after a successful revive response.
- **No completion-event guarantees on the response.** Unlike agent restart, revive awaits the restart-agent flow synchronously and returns when the relaunch has been dispatched; agent readiness is observed downstream (e.g., via the session-ready signal on the event bus), not in the response.

- **A kept agent status is not evidence that the revived agent is running.** Revival keeps the status whether or not the relaunched process comes up, and no `no_start` stall flags a relaunch that never came up.

## See Also

- ~/.teleclaude/docs/general/principle/session-lifecycle.md — unfinished governed sessions remain available for their continuing work.

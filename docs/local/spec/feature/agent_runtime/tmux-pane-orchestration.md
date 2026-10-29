---
description: 'Host-pane orchestration primitives that agent_runtime uses to host agent CLI processes — session creation, pane snapshot capture, key injection, signaling, kill, and liveness probing.'
visibility: 'public'
---

# Tmux Pane Orchestration — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The low-level host-pane orchestration surface that `agent_runtime` uses to host a supervised agent CLI inside a multiplexed terminal pane. Every live agent CLI process — Claude, Codex, Gemini — runs inside exactly one detached host pane created and managed through this surface. The bridge exposes one primitive surface that fans out to four concerns: host-pane creation/teardown, pane snapshot capture, key and signal injection, and subprocess-timeout discipline.

The surface is stateless. Every function that creates or changes a host pane shells out to the configured terminal multiplexer binary (default `tmux`; on macOS the launcher through which panes reach protected files), while five reads that only query the running server — the polling pane snapshot, pane capture, the session existence check, the session listing and the pane tty query — shell out to the multiplexer client the launcher runs, selected as the launcher selects it. Every other function reads configuration lazily for per-call values, and wraps each subprocess call in a timeout envelope that raises a subprocess-timeout error on hang. No in-process host-pane table is held — the only authoritative state lives in the multiplexer server. Higher-level callers (session-lifecycle creation/end flows, session-cleanup orphan sweeps, the polling cadence loop) consume this surface; this surface owns the host-pane interaction end-to-end and reports successes and failures via return values and structured logs.

## Canonical fields

### Use cases

#### UC-TPO1: Concurrent host-pane snapshots are bounded against the multiplexer server

#### UC-TPO2: An operator can inspect scrollback while requested input reaches the agent

```
Given a person asks their agent to submit text to the foreground program while they inspect earlier output
When the agent sends the text
Then the foreground program receives the submitted text whether the operator is viewing scrollback or live output
```

#### UC-TPO3: Whole-server loss follows unavailable host-pane liveness

### Cross-context references

`agent_runtime` owns host-pane orchestration end-to-end; no other bounded context calls into the bridge directly. Adjacent dependencies:

- **config** — the configured multiplexer binary selects the underlying terminal multiplexer; the global and per-project env allowlists name ambient env vars that may enter agent sessions; TeleClaude-owned runtime env preserves appearance, locale, voice selector, and log-level keys while stripping NO_COLOR after session creation; an env override variable overrides the per-session tmpdir root from configuration defaults. Subprocess timeout budgets are surface-internal constants, not currently sourced from config.

- **Internal agent_runtime consumers** — session-lifecycle (session start, end, kill), session-cleanup (orphan sweeps), the polling cadence loop (snapshot-driven cadence transitions), agent-coordinator (signal escalation, control queue).
- No identity, integration, workflow, knowledge, or session_mirrors call this surface.

## Known caveats

- **The snapshot concurrency bound trades tail latency for server headroom.** The multiplexer server is single-threaded, so unbounded snapshot fan-out across per-session pollers contends on it and inflates the process's open descriptor count. The bound is a surface-internal constant, in the same family as the subprocess timeout budgets and likewise not sourced from config. It caps concurrent snapshot clients, so under a burst a poller can wait for a slot and its tick lands late; the wait is bounded because every in-flight client is killed at its timeout budget. Only snapshot collection is bounded — the other primitives (create, send-keys, kill, liveness probes) are not on the polling hot path and spawn freely.

- **Pane capture line budgets and message char budgets are separate.** The capture primitives accept an optional capture-line budget; when omitted, the budget defaults to the configured default (currently 200). Session-data fallback callers use a smaller line budget for the pane read, then apply their independent character-budget on the resulting text.
- **send-keys auto-creates on miss.** If the named host pane is gone (crashed, killed externally), send-keys silently calls the ensure primitive and the text is delivered to a freshly created pane with no prior state. This is explicit: "Previous state is lost — this is NOT recovery, just creating a new session so the user can continue working." Callers that need miss-as-error must use the existing-pane variant (with their own existence check) instead.

- **Per-session tmpdir is the Claude Code unix-socket workaround.** Claude Code's filesystem watcher can crash on macOS if TMPDIR contains stray unix sockets (e.g., docker CLI sockets). The bridge mitigates this by giving every host pane its own mode-700 tmpdir cleared of temporary entries, retaining only its declaration record, rather than sharing the global one. The directory is created on session start and not removed by the kill primitive — cleanup lives with higher-level lifecycle code.

- **Setup-chain failures are non-fatal but only logged.** After create succeeds, the environment-setup chain runs and is allowed to fail — a per-step descriptor reconstructs which step failed from chain markers in stdout. The session is still considered created. Symptoms (color leakage, premature destroy on detach) may surface later if a step silently failed.
- **Pipe-pane wake-signal interpretation is internal.** The pipe attach/detach primitives attach/detach a command to the pane's output stream. This byte-arrival signal is used as the Codex wake mechanism (any bytes set a dirty flag, triggering a snapshot on the next cadence cycle). The plumbing primitives are stable; the semantic interpretation upstream may diverge — the bridge itself merely manages the multiplexer attach/detach.
- **SIGKILL targets the first child, not the full process tree.** The hard-kill primitive reads the pane shell process id, looks up its children, and sends SIGKILL to the FIRST child returned. If the agent CLI spawned a descendant tree (subprocesses, helpers), only the foreground child is killed. The shell typically reaps the orphans, but a misbehaving descendant chain can survive. The whole-pane kill primitive is the heavier hammer that tears down the entire host pane.
- **The update primitive only affects NEW processes.** Setting an env var on the host pane updates the multiplexer environment for future child processes; the already-running pane shell and the agent CLI in it do NOT see the update. Callers needing to push env into a live process must restart the session.
- **stderr-substring matching for missing-pane detection in the snapshot primitive.** The unavailable-host-pane path recognizes the multiplexer diagnostics for an absent target pane or server. A future multiplexer version that changes those diagnostics would surface as a raised error instead of an unavailable-pane snapshot.

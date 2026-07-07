---
description: 'Host-pane orchestration primitives that agent_runtime uses to host agent CLI processes — session creation, pane snapshot capture, key injection, signaling, kill, and liveness probing.'
visibility: 'public'
---

# Tmux Pane Orchestration — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The low-level host-pane orchestration surface that `agent_runtime` uses to host a supervised agent CLI inside a multiplexed terminal pane. Every live agent CLI process — Claude, Codex, Gemini — runs inside exactly one detached host pane created and managed through this surface. The bridge exposes one primitive surface that fans out to four concerns: host-pane creation/teardown, pane snapshot capture, key and signal injection, and subprocess-timeout discipline.

The surface is stateless. Every function shells out to the configured terminal multiplexer binary (default `tmux`), reads configuration lazily for per-call values, and wraps each subprocess call in a timeout envelope that raises a subprocess-timeout error on hang. No in-process host-pane table is held — the only authoritative state lives in the multiplexer server. Higher-level callers (session-lifecycle creation/end flows, session-cleanup orphan sweeps, the polling cadence loop) consume this surface; this surface owns the host-pane interaction end-to-end and reports successes and failures via return values and structured logs.

## Canonical fields

### Use cases

#### Host-pane creation is idempotent through ensure-host-pane

```
Given agent_runtime needs a host pane named "<teleclaude-prefix><session_id>" for a session id
When ensure-host-pane(name, working_dir, session_id, env_vars) is called
Then the bridge first checks whether the host pane already exists
And returns success immediately if it does
And otherwise invokes the create primitive to spawn it detached
And on creation failure, re-checks existence to absorb create/has-pane race
And returns success if the pane is present at function exit, failure otherwise
```

#### A fresh host pane is created with a TeleClaude-controlled shell and a sealed env

```
Given the create primitive is invoked for (name, working_dir, session_id, env_vars)
When the bridge builds the create command
Then a per-session tmpdir is materialized under the configured per-session tmpdir base, keyed by the session id
And the directory is recreated empty with restrictive mode to drop any stray unix sockets
And the TeleClaude-controlled env dict injects TELECLAUDE_HOME, the TeleClaude shell selector, the configured rc roots, PATH, COLORTERM=truecolor, UV_NO_SYNC=1, the working-directory tracking marker, and TMPDIR/TMP/TEMP all pointing at the per-session tmpdir
And authorized agent env vars are resolved from the global and per-project env allowlists
And TeleClaude-owned non-secret runtime env vars are preserved for the agent pane, including appearance, locale, voice selectors, and the platform log level
And common runtime env filtering uses one shared allowlist for appearance and locale keys, with TUI and agent panes adding only surface-specific extras
And agent env vars are written to a private file under the per-session tmpdir
And each env var name is validated against a strict identifier pattern — invalid names are refused
And the multiplexer is invoked to create a detached session with only TeleClaude-controlled values surfaced
And the shell command sources the private agent env file before executing the TeleClaude shell
And on success, a follow-up environment-setup chain runs to drop NO_COLOR and set hooks, with per-step markers logged so the failing step can be identified
And the call returns success on a zero-exit create, failure otherwise (including subprocess-timeout)
```

#### Per-session tmpdir layout

```
Given a host pane is created for session id S
When the per-session tmpdir is prepared
Then the path is anchored under the configured per-session tmpdir base
And the base defaults to <TELECLAUDE_HOME>/tmp/sessions, overridable via the configured override variable
And the safe-component helper returns the raw id when it matches the safe pattern, otherwise a SHA-256 prefix
And any prior contents (including unix sockets) are removed before creation
And the directory is created with restrictive mode
And later requests for the tmpdir return its path if it still exists, or nothing
```

#### A single host-pane snapshot returns the polling state

```
Given the polling cadence loop probes a host pane
When the snapshot primitive is invoked with a capture-line budget N
Then ONE multiplexer process runs a chained command:
    capture pane output, emit a boundary marker, then list pane-dead flags
And the boundary marker partitions stdout into pane output (raw) and pane-dead lines
And if N is omitted or non-positive, N defaults to the configured default; hot poller callers pass their own smaller window
And the result is a pane snapshot carrying (pane exists, pane dead, output raw, output normalized)
And output normalized strips ANSI, normalizes CRLF/CR to LF, and right-strips each line
And if stderr matches "can't find" or "no such" (case-insensitive), the snapshot reports the pane as absent without raising
And other nonzero exits raise; subprocess hangs raise subprocess-timeout
```

#### `capture-pane` alone returns the raw capture body

```
Given a caller wants only the pane text, not the liveness probe
When the capture primitive is invoked with a capture-line budget N
Then the multiplexer is invoked to capture pane output only
And on success, the raw decoded stdout is returned
And on nonzero exit the call logs and returns an empty string
And on subprocess timeout or OS error the exception is re-raised
And the same default fallback applies when the budget is omitted
```

#### Send-keys uses the load-buffer / paste / submit pipeline

```
Given the send-keys primitive is called with (host pane name, text, session id, working_dir, active agent)
When the host pane is ensured (creating it fresh on miss — previous state is lost; this is NOT recovery)
Then text is delivered through the three-stage pipeline:
    1. Load a uniquely-named paste buffer from stdin (bypasses multiplexer argument-length limits)
    2. Paste the buffer with bracketed-paste markers, preserving LF
    3. Wait a small ordering margin so the multiplexer flushes the close marker before the discrete submit
    4. Send a discrete submit keystroke (treated as submit by all three agent CLIs)
And the paste buffer is always cleaned up in a finalizer (cleanup errors are logged but never override the operation result)
And if the active agent is Gemini, every literal '!' in text is replaced with '\!' (Gemini CLI bug workaround)
And the call returns success on every stage success, failure on any stage failure
```

#### send-keys-existing-host-pane skips the auto-create

```
Given a caller has already verified the host pane exists
When the existing-pane variant is invoked
Then the same load/paste/submit pipeline runs without re-checking existence
And subprocess-timeout is caught and converted to a structured log + failure return
And the redundant existence check is intentionally omitted to save one subprocess call
```

#### paste-text-existing-host-pane skips submit

```
Given a caller has already verified the host pane exists
When the paste-only existing-pane variant is invoked
Then it runs the same load-buffer, paste-buffer, and cleanup stages as send-keys-existing-host-pane
And it does NOT wait the post-paste submit gap
And it does NOT send a submit keystroke
And the caller is responsible for observing pane state and submitting later if needed
```

#### send-keys-to-tty is the non-pane escape hatch

```
Given a session is hosted on a controlling TTY rather than a multiplexed pane
When the TTY variant is called
Then the tty is opened off the event loop
And bytes are injected one at a time via the TTY ioctl that mimics typed input, retrying on transient errors up to 5 seconds
And if the path looks like a PTY master, a direct write fallback is used
And the call returns success on success, failure on errors
```

#### Signal injection: SIGINT and SIGTERM via key commands, SIGKILL via shell-child lookup

```
Given the signal primitive is called for a host pane
When the signal is SIGINT
Then the multiplexer is asked to send Ctrl-C into the pane
When the signal is SIGTERM
Then the multiplexer is asked to send Ctrl-\\ into the pane
When the signal is SIGKILL
Then the bridge reads the pane's shell process id
And looks up the foreground child of that shell
And sends a hard kill to the first child returned
And returns failure if no shell id, no children, or any subprocess fails
```

#### Liveness probes

```
Given a poller needs to know whether the agent CLI is alive in a host pane
When the current-command probe is called
Then the multiplexer reports the pane's current foreground command name (or nothing)

When the running-process check is called
Then it returns true iff the current command exists and differs from the user's shell basename

When the wait-for-shell-ready probe is called with a timeout
Then it polls the current command until the foreground command equals the user's shell, returning success on hit, failure on timeout

When the pane-dead check is called
Then the multiplexer reports pane-dead flags per pane
And the check returns true iff at least one pane line is present AND every numeric line equals 1
```

#### Pipe-pane attach / detach

```
Given pipe-pane attachment for byte-arrival wake signaling
When the attach primitive is called
Then the multiplexer attaches a command to the pane's output stream (append mode)
And returns success on a clean attach

When the detach primitive is called
Then the multiplexer is asked to sever the pipe
And returns success on clean detach
```

#### Subprocess timeout envelope

```
Given any multiplexer invocation
When the timeout-guarded wait or communicate primitive is awaited
Then a timeout guard wraps the call with the supplied timeout
And on timeout, the process is terminated and a 2s grace wait is attempted
And a subprocess-timeout error is raised carrying the operation name, timeout, and process id
And the timeout budgets are categorized as quick (5s), default (30s), and long (60s)
And nearly all bridge calls use the quick budget
```

#### Killing a host pane cascades to all panes

```
Given the kill primitive is called for a host pane
When the multiplexer is asked to kill the session
Then the multiplexer terminates the session, every pane, every child of every pane's shell — the SHELL exits, which reaps the agent CLI and any subprocess tree it spawned
And the per-session tmpdir is NOT removed here (that lives with session lifecycle/cleanup callers)
And the call returns success on a clean kill
```

### Cross-context references

`agent_runtime` owns host-pane orchestration end-to-end; no other bounded context calls into the bridge directly. Adjacent dependencies:

- **config** — the configured multiplexer binary selects the underlying terminal multiplexer; the global and per-project env allowlists name ambient env vars that may enter agent sessions; TeleClaude-owned runtime env preserves appearance, locale, voice selector, and log-level keys while stripping NO_COLOR after session creation; an env override variable overrides the per-session tmpdir root from configuration defaults. Subprocess timeout budgets are surface-internal constants, not currently sourced from config.

- **Internal agent_runtime consumers** — session-lifecycle (session start, end, kill), session-cleanup (orphan sweeps), the polling cadence loop (snapshot-driven cadence transitions), agent-coordinator (signal escalation, control queue).
- No identity, integration, workflow, knowledge, or session_mirrors call this surface.

## Known caveats

- **Pane capture line budgets and message char budgets are separate.** The capture primitives accept an optional capture-line budget; when omitted, the budget defaults to the configured default (currently 200). Session-data fallback callers use a smaller line budget for the pane read, then apply their independent character-budget on the resulting text.
- **send-keys auto-creates on miss.** If the named host pane is gone (crashed, killed externally), send-keys silently calls the ensure primitive and the text is delivered to a freshly created pane with no prior state. This is explicit: "Previous state is lost — this is NOT recovery, just creating a new session so the user can continue working." Callers that need miss-as-error must use the existing-pane variant (with their own existence check) instead.
- **Per-session tmpdir is the Claude Code unix-socket workaround.** Claude Code's filesystem watcher can crash on macOS if TMPDIR contains stray unix sockets (e.g., docker CLI sockets). The bridge mitigates this by giving every host pane its own freshly-created, mode-700, empty tmpdir rather than sharing the global one. The directory is created on session start and not removed by the kill primitive — cleanup lives with higher-level lifecycle code.
- **Setup-chain failures are non-fatal but only logged.** After create succeeds, the environment-setup chain runs and is allowed to fail — a per-step descriptor reconstructs which step failed from chain markers in stdout. The session is still considered created. Symptoms (color leakage, premature destroy on detach) may surface later if a step silently failed.
- **Pipe-pane wake-signal interpretation is internal.** The pipe attach/detach primitives attach/detach a command to the pane's output stream. This byte-arrival signal is used as the Codex wake mechanism (any bytes set a dirty flag, triggering a snapshot on the next cadence cycle). The plumbing primitives are stable; the semantic interpretation upstream may diverge — the bridge itself merely manages the multiplexer attach/detach.
- **SIGKILL targets the first child, not the full process tree.** The hard-kill primitive reads the pane shell process id, looks up its children, and sends SIGKILL to the FIRST child returned. If the agent CLI spawned a descendant tree (subprocesses, helpers), only the foreground child is killed. The shell typically reaps the orphans, but a misbehaving descendant chain can survive. The whole-pane kill primitive is the heavier hammer that tears down the entire host pane.
- **The update primitive only affects NEW processes.** Setting an env var on the host pane updates the multiplexer environment for future child processes; the already-running pane shell and the agent CLI in it do NOT see the update. Callers needing to push env into a live process must restart the session.
- **stderr-substring matching for missing-pane detection in the snapshot primitive.** The "session does not exist" path is detected by matching "can't find" or "no such" in stderr (case-insensitive). A future multiplexer version that changes its error wording would silently break this branch and surface as a raised error instead of a "pane absent" snapshot.

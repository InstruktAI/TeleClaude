---
id: 'project/spec/feature/agent_runtime/tmux-pane-orchestration'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'tmux-bridge primitive surface that v1 agent_runtime uses to host agent CLI processes — session creation, pane snapshot capture, key injection, signaling, kill, and liveness probing.'
---

# Tmux Pane Orchestration — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The low-level tmux orchestration surface that v1 `agent_runtime` uses to host a supervised agent CLI inside a tmux pane. Every live agent CLI process — Claude, Codex, Gemini — runs inside exactly one detached tmux session created and managed through this surface. The bridge exposes one primitive surface, the `teleclaude.core.tmux_bridge` package, that fans out to four concerns: session creation/teardown, pane snapshot capture, key and signal injection, and subprocess-timeout discipline.

The surface is stateless. Every function shells out to the `tmux` binary configured in `config.computer.tmux_binary` (default `tmux`), reads `config` lazily for per-call values, and wraps each `asyncio.create_subprocess_exec` call in a timeout envelope that raises `SubprocessTimeoutError` on hang. No in-process tmux session table is held — the only authoritative state lives in the tmux server. Higher-level callers (session_lifecycle creation/end flows, session_cleanup orphan sweeps, the polling cadence loop) consume this surface; this surface owns the tmux interaction end-to-end and reports successes and failures via return values and structured logs.

## Canonical fields

### Behavioral contract

#### Tmux session creation is idempotent through `ensure_tmux_session`

```
Given agent_runtime needs a tmux session named "tc_<session_id>" for a session_id
When ensure_tmux_session(name, working_dir, session_id, env_vars) is called
Then the bridge first calls session_exists(name, log_missing=False)
And returns True immediately if the session already exists
And otherwise invokes _create_tmux_session to create it detached
And on creation failure, re-checks existence to absorb create/has-session race
And returns True if the session is present at function exit, False otherwise
```

#### A fresh tmux session is created with a TeleClaude-controlled shell and a sealed env

```
Given _create_tmux_session(name, working_dir, session_id, env_vars) is called
When the bridge builds the tmux new-session command
Then a per-session TMPDIR is materialized under TMP_SESSIONS_DIR / safe_session_tmp_component(session_id)
And the directory is recreated empty with mode 0700 to drop any stray unix sockets
And the env dict injects TELECLAUDE_HOME, SHELL=teleclaude-shell, ZDOTDIR, BASH_ENV, ENV, PATH, COLORTERM=truecolor, UV_NO_SYNC=1, ZSH_LAST_WORKING_DIRECTORY=1, TMPDIR/TMP/TEMP all pointing at the per-session TMPDIR
And each env var is validated against ^[A-Za-z_][A-Za-z0-9_]*$ — invalid names raise ValueError
And tmux is invoked as `tmux new-session -d -s <name> -c <working_dir> [-e VAR=VAL ...] <shell_command>` with shell_command=`VAR=val ... exec teleclaude-shell`
And on success, a follow-up `set-environment -u NO_COLOR ; set-option destroy-unattached off ; set-hook client-detached run-shell true` setup chain runs, with per-step markers logged so the failing step can be identified
And the call returns True on tmux returncode==0, False on returncode!=0 or SubprocessTimeoutError
```

#### Per-session TMPDIR layout

```
Given a tmux session is created for session_id S
When _prepare_session_tmp_dir(S) runs
Then the path is TMP_SESSIONS_DIR / safe_session_tmp_component(S)
And TMP_SESSIONS_DIR defaults to ${TELECLAUDE_HOME}/tmp/sessions, overridable via TELECLAUDE_SESSION_TMPDIR_BASE
And safe_session_tmp_component returns the raw id when it matches [A-Za-z0-9._-]{1,128}, otherwise sha256(id)[:32]
And any prior contents (including unix sockets) are removed before creation
And the directory is created with mode 0700
And get_session_tmpdir(S) later returns the path if it still exists, or None
```

#### A single tmux snapshot returns the polling state

```
Given the polling cadence loop probes session_name
When collect_pane_snapshot(session_name, capture_lines=N) is invoked
Then ONE tmux process runs the chained command:
    capture-pane -t <name> -p -J -e -S -<N> ; display-message -p <BOUNDARY_MARKER> ; list-panes -t <name> -F '#{pane_dead}'
And the boundary marker partitions stdout into pane output (raw) and pane_dead lines
And if N is omitted or non-positive, N defaults to UI_MESSAGE_MAX_CHARS (3900) — see Known caveats
And the result is a PaneSnapshot(session_exists, pane_dead, output_raw, output_normalized)
And output_normalized strips ANSI, normalizes CRLF/CR to LF, and rstrips each line
And if tmux stderr matches "can't find" or "no such" (case-insensitive), session_exists=False is returned without raising
And other nonzero exits raise ValueError; subprocess hangs raise SubprocessTimeoutError
```

#### `capture_pane` alone returns the raw capture body

```
Given a caller wants only the pane text, not the liveness probe
When capture_pane(session_name, capture_lines=N) is invoked
Then tmux is invoked as `capture-pane -t <name> -p -J -e -S -<N>`
And on returncode==0, the raw decoded stdout is returned
And on returncode!=0 the call logs and returns "" (empty string)
And on SubprocessTimeoutError or OSError the exception is re-raised
And the same UI_MESSAGE_MAX_CHARS fallback applies when capture_lines is omitted
```

#### Send-keys uses the load-buffer / paste-buffer / send-keys C-m pipeline

```
Given send_keys(session_name, text, session_id, working_dir, active_agent) is called
When the session is ensured (via ensure_tmux_session, creating it fresh on miss — previous state is lost; this is NOT recovery)
Then text is delivered through the three-stage pipeline:
    1. tmux load-buffer -b telec-<uuid> - (text piped to stdin to bypass tmux argv length limits)
    2. tmux paste-buffer -p -r -t <name> -b telec-<uuid> (bracketed paste DECSET 2004 markers, preserves LF)
    3. asyncio.sleep(0.2) ordering margin so tmux flushes the close marker before the discrete submit
    4. tmux send-keys -t <name> C-m (discrete Enter, treated as submit by all three agent CLIs)
And the buffer is always deleted in a finally block via `tmux delete-buffer -b telec-<uuid>` (cleanup errors are logged but never override the operation result)
And if active_agent == "gemini", every literal '!' in text is replaced with '\!' (Gemini CLI bug workaround)
And the call returns True on every stage success, False on any stage failure
```

#### `send_keys_existing_tmux` skips the auto-create

```
Given a caller has already verified session_name exists
When send_keys_existing_tmux(session_name, text, active_agent, timeout) is called
Then the same load/paste/submit pipeline runs without re-checking existence
And SubprocessTimeoutError is caught and converted to False with structured log
And the redundant existence check is intentionally omitted to save one subprocess call
```

#### `send_keys_to_tty` is the non-tmux escape hatch

```
Given a session is hosted on a controlling TTY rather than a tmux pane
When send_keys_to_tty(tty_path, text, send_enter=True) is called
Then the tty is opened with O_RDWR | O_NOCTTY off the asyncio loop
And bytes are injected byte-by-byte via fcntl.ioctl(fd, TIOCSTI, byte) with EAGAIN/EWOULDBLOCK/EINTR/ENOMEM retry up to 5s
And if the path looks like a PTY master ("pty*", "ptys*", "ptyp*"), os.write is used as a fallback
And the call returns True on success, False on OSError or ValueError
```

#### Signal injection: SIGINT and SIGTERM via send-keys, SIGKILL via pgrep+kill

```
Given send_signal(session_name, signal) is called
When signal is SIGINT
Then tmux is invoked as `send-keys -t <name> C-c`
When signal is SIGTERM
Then tmux is invoked as `send-keys -t <name> C-\\`
When signal is SIGKILL
Then the bridge calls `display-message -p '#{pane_pid}'` to read the shell PID
And calls `pgrep -P <shell_pid>` to find the foreground child
And sends `kill -9 <child_pid>` to the first child returned
And returns False if no shell PID, no children, or any subprocess fails
```

#### Liveness probes

```
Given a poller needs to know whether the agent CLI is alive in session_name
When get_current_command(session_name) is called
Then tmux is invoked as `display-message -p -t <name> '#{pane_current_command}'` and returns the trimmed command name or None

When is_process_running(session_name) is called
Then it returns True iff get_current_command result exists and != the user's shell basename (computed at import from $SHELL or pwd entry)

When wait_for_shell_ready(session_name, timeout_s=8.0, poll_interval_s=0.2) is called
Then it polls get_current_command until the foreground command equals the user's shell, returning True on hit, False on timeout

When is_pane_dead(session_name) is called
Then it invokes `list-panes -t <name> -F '#{pane_dead}'`
And returns True iff at least one pane line is present AND every numeric line equals 1
```

#### Pipe-pane attach / detach

```
Given pipe-pane attachment for byte-arrival wake signaling
When start_pipe_pane(session_name, command) is called
Then tmux is invoked as `pipe-pane -t <name> -o <command>` (the -o flag toggles append-pipe mode)
And returns True on returncode==0

When stop_pipe_pane(session_name) is called
Then tmux is invoked as `pipe-pane -t <name>` with no command (this severs the pipe)
And returns True on returncode==0
```

#### Subprocess timeout envelope

```
Given any tmux invocation
When wait_with_timeout(process, timeout, operation) or communicate_with_timeout(process, input, timeout, operation) is awaited
Then asyncio.wait_for guards the call with the supplied timeout
And on TimeoutError, the process is killed and a 2s grace wait_for(process.wait()) is attempted
And SubprocessTimeoutError(operation, timeout, pid) is raised (chained via `from None`)
And the timeout constants are SUBPROCESS_TIMEOUT_QUICK=5.0, SUBPROCESS_TIMEOUT_DEFAULT=30.0, SUBPROCESS_TIMEOUT_LONG=60.0
And nearly all tmux-bridge calls use the QUICK budget
```

#### Killing a tmux session cascades to all panes

```
Given kill_session(session_name) is called
When tmux is invoked as `kill-session -t <name>`
Then tmux terminates the session, every pane, every child of every pane's shell — the SHELL exits, which reaps the agent CLI and any subprocess tree it spawned
And the per-session TMPDIR is NOT removed here (that lives with session lifecycle/cleanup callers)
And the call returns True on returncode==0
```

### Implementation pointers (v1)

- Public surface: `teleclaude/core/tmux_bridge/__init__.py:1`
- Session creation and TMPDIR layout: `teleclaude/core/tmux_bridge/_session.py:48` (`_get_session_tmp_basedir`), `:67` (`safe_session_tmp_component`), `:72` (`_prepare_session_tmp_dir`), `:111` (`_create_tmux_session`), `:276` (`ensure_tmux_session`), `:309` (`update_tmux_session`)
- Pane snapshot + capture + liveness: `teleclaude/core/tmux_bridge/_pane.py:34` (`PaneSnapshot`), `:107` (`capture_pane`), `:171` (`collect_pane_snapshot`), `:234` (`kill_session`), `:279` (`session_exists` with diagnostic-rich logging), `:353` (`get_current_command`), `:389` (`wait_for_shell_ready`), `:407` (`is_process_running`), `:415` (`is_pane_dead`), `:465` (`start_pipe_pane`), `:487` (`stop_pipe_pane`)
- Key and signal injection: `teleclaude/core/tmux_bridge/_keys.py:41` (`send_keys`), `:85` (`send_keys_existing_tmux`), `:123` (`send_keys_to_tty`), `:173` (`_send_keys_tmux` — the load-buffer/paste-buffer/C-m pipeline), `:314` (`send_signal`), `:421+` (`send_escape`, `send_ctrl_key`, `send_tab`, `send_shift_tab`, `send_backspace`, `send_enter`, `send_arrow_key`)
- Timeout envelope: `teleclaude/core/tmux_bridge/_subprocess.py:11` (timeout constants), `:16` (`SubprocessTimeoutError`), `:40` (`wait_with_timeout`), `:78` (`communicate_with_timeout`)
- Live callers (within agent_runtime): session_lifecycle creation/end flows, `teleclaude/core/session_cleanup.py` orphan sweeps, the polling cadence loop (consumer of `collect_pane_snapshot`), `teleclaude/core/agent_coordinator/` signal handlers (consumers of `send_signal`)

### Cross-context references

`agent_runtime` owns tmux orchestration end-to-end; no other bounded context calls into `tmux_bridge` directly. Adjacent dependencies:

- **config** — `config.computer.tmux_binary` selects the tmux binary path; the env override `TELECLAUDE_SESSION_TMPDIR_BASE` overrides the per-session TMPDIR root from `paths.TMP_SESSIONS_DIR`. Subprocess timeout constants are module-level (`SUBPROCESS_TIMEOUT_QUICK`, `..._DEFAULT`, `..._LONG`), not currently sourced from config.
- **Internal `agent_runtime` consumers** — session_lifecycle (session start, end, kill), session_cleanup (orphan tmux sweeps), the polling cadence loop (snapshot-driven cadence transitions), agent_coordinator (signal escalation, control queue).
- No identity, integration, workflow, knowledge, or session_mirrors call this surface.

## Known caveats

- **`capture_lines` parameter conflates a char budget with a line count.** Both `capture_pane` and `collect_pane_snapshot` accept `capture_lines: int | None`; when omitted, the value defaults to `UI_MESSAGE_MAX_CHARS` (3900) and is passed verbatim as `-S -<N>` to tmux. tmux interprets `-S -N` as "start N lines back in the scrollback," not as a character budget. The effect is that the default fetches 3900 LINES of scrollback when the constant is intended to bound MESSAGE CHARS. v1 has lived with this conflation. v2 is expected to separate the two concerns.
- **`send_keys` auto-creates on miss.** If the named tmux session is gone (crashed, killed externally), `send_keys` silently calls `ensure_tmux_session` and the text is delivered to a freshly created session with no prior state. The docstring is explicit: "Previous state is lost - this is NOT recovery, just creating a new session so the user can continue working." Callers that need miss-as-error must call `send_keys_existing_tmux` (with their own existence check) instead.
- **Per-session TMPDIR is the Claude Code unix-socket workaround.** Claude Code's `fs.watch` can crash on macOS if TMPDIR contains stray unix sockets (e.g., `docker_cli_*`). The bridge mitigates this by giving every tmux session its own freshly-created, 0700, empty TMPDIR rather than sharing the global one. The directory is created on session start and not removed by `kill_session` — cleanup lives with higher-level lifecycle code.
- **Setup chain failures are non-fatal but only logged.** After `new-session` succeeds, the `set-environment -u NO_COLOR ; set-option destroy-unattached off ; set-hook client-detached run-shell true` chain runs and is allowed to fail — `_describe_setup_chain_failure` reconstructs which step failed from chain markers in stdout. The session is still considered created. Symptoms (color leakage, premature destroy on detach) may surface later if a step silently failed.
- **Pipe-pane wake-signal interpretation is v1-specific.** `start_pipe_pane` / `stop_pipe_pane` attach/detach a command to the pane's output stream. v1 uses this byte-arrival signal as the Codex wake mechanism (any bytes set `wake_dirty=true`, triggering a snapshot on the next cadence cycle). The plumbing primitives are stable; the semantic interpretation upstream may diverge in v2 — the bridge itself merely manages the tmux attach/detach.
- **SIGKILL targets the first child, not the full process tree.** `send_signal(SIGKILL)` reads the pane PID, runs `pgrep -P <shell_pid>`, and SIGKILLs the FIRST child returned. If the agent CLI spawned a descendant tree (subprocesses, helpers), only the foreground child is killed. The shell typically reaps the orphans, but a misbehaving descendant chain can survive. `kill_session` is the heavier hammer that tears down the whole tmux session.
- **`update_tmux_session` only affects NEW processes.** `setenv -t <name> VAR VAL` updates the tmux session environment for future child processes; the already-running pane shell and the agent CLI in it do NOT see the update. Callers needing to push env into a live process must restart the session.
- **stderr-substring matching for missing-session detection in `collect_pane_snapshot`.** The "session does not exist" path is detected by `"can't find" in stderr.lower() or "no such" in stderr.lower()`. A future tmux version that changes its error wording would silently break this branch and surface as a raised `ValueError` instead of `session_exists=False`.

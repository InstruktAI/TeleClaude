# Bug: Enter key submission after agent command injection is brittle and fails regularly

## Symptom

Enter key submission after agent command injection is brittle and fails regularly

## Detail

## Symptom

When dispatching a Gemini worker via `telec sessions run`, the /next-bugs-fix command is injected into the Gemini CLI prompt but the enter key submission fails silently. Gemini launches, shows its prompt with the command text visible, but never processes it — the session sits idle at the input prompt indefinitely.

## Reproduction

1. `telec sessions run --command /next-bugs-fix --args fix-git-wrapper-reset --project /Users/Morriz/Workspace/InstruktAI/TeleClaude --agent gemini --mode med --subfolder trees/fix-git-wrapper-reset`
2. Tail the session — Gemini shows its startup banner and prompt but no assistant response
3. The command text appears in the terminal but was never submitted

## Evidence

Session b7ce4768-a64c-478c-a951-839cc728c1a1 (2026-03-17) — Gemini sat at prompt for 10+ minutes without processing the injected command.

## Impact

Gemini workers cannot be dispatched reliably as fallback when Claude hits rate limits. The orchestrator has no way to detect the failure except by polling and finding no output.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

The command injection flow for `agent_then_message` follows this path:

1. `start_agent` sends the agent CLI command to tmux (e.g. `gemini --yolo -m ...`)
2. `_wait_for_output_stable` polls `capture-pane` every 0.2s, waiting for output to stop changing for N seconds (inactivity-based readiness)
3. Message text + Enter is injected via `_send_keys_tmux`

Three distinct failure modes were identified:

**Mode 1: "Agent launches with no input at all"** — `_wait_for_output_stable` fires prematurely. Gemini's startup has two phases: banner rendering (fast, 1-2s) then MCP server/context loading (3-10s). A brief pause between phases triggers the quiet-window, but the TUI is not yet at its input prompt. The injected text lands in a partially initialized TUI and is swallowed.

**Mode 2: "Command visible but Enter not processed"** — Same root cause: the TUI receives the text (visible in the input box) but is not yet in a state where it processes Enter. The `_confirm_command_acceptance` fallback then fires but its output-change detection sees the text in the input box as "changed" and returns True — even though Gemini never submitted the message.

**Mode 3: "Works sometimes"** — When system load is low and Gemini's loading time is consistent, the 4-second quiet window (1.0s + 3.0s Gemini extra) happens to align with the true ready state.

The underlying problem is that `_wait_for_output_stable` treats inactivity as a proxy for readiness. This is brittle because agent startup output is non-monotonic: brief pauses during loading phases trigger false-positive stabilization. The Gemini-specific `GEMINI_START_EXTRA_DELAY_S` (3s) was a timer-based workaround, not a fix.

Each agent CLI renders a specific marker in the terminal only when it has finished loading and is ready to accept keystrokes:

- **Gemini**: `Type your message or @path/to/file` (input box placeholder, verified by capture-pane probe)
- **Claude**: `\u276f ` (U+276F input prompt character, verified by capture-pane probe)
- **Codex**: `? for shortcuts` (status bar shortcut hint, verified by capture-pane probe)

## Root Cause

`_wait_for_output_stable` uses inactivity (output unchanged for N seconds) as a proxy for agent readiness. This is not event-driven — it fires on any quiet period during startup, including loading pauses before the TUI input prompt appears. The Gemini-specific 3-second extra quiet window was a timer-based heuristic that reduced but did not eliminate the race.

## Fix Applied

Added `AGENT_PROMPT_READY_MARKERS` dict and `_wait_for_agent_prompt_ready` method to `daemon_session.py`. Each entry maps an agent name to the terminal substring that appears only when the agent TUI is at its input prompt (verified by live capture-pane probing of each CLI).

`_handle_agent_then_message` now calls `_wait_for_agent_prompt_ready` instead of `_wait_for_output_stable`. The new method:

1. Calls `_wait_for_output_contains(session, marker, AGENT_PROMPT_READY_TIMEOUT_S)` for agents with a known marker — exits as soon as the marker appears, not on a timer
2. Falls back to inactivity detection if the marker is absent or unknown

The Gemini-specific `quiet_s += GEMINI_START_EXTRA_DELAY_S` timer branch is removed; Gemini now uses the same marker-based path as other agents.

Files changed:

- `teleclaude/daemon_session.py` — `AGENT_PROMPT_READY_MARKERS`, `AGENT_PROMPT_READY_TIMEOUT_S`, `_wait_for_agent_prompt_ready`, updated `_handle_agent_then_message`
- `tests/unit/test_daemon_session.py` — 4 new behavioral tests for the readiness detection

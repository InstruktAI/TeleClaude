# tmux Session Output Observation

## Purpose

Document tmux behaviors relevant to observing AI agent session output in TeleClaude: pane capture, output piping, and session lifecycle. Focused on the subset of tmux's surface used by `teleclaude/core/tmux_bridge.py` and `teleclaude/core/output_poller.py`.

## capture-pane

### Core Behavior

`capture-pane` (alias `capturep`) returns the **rendered state** of a pane's terminal grid — not the raw byte stream that produced it. tmux maintains an internal terminal emulator (VT100/xterm-compatible) that processes all application output. `capture-pane` reads from this emulator's cell grid, producing text that reflects cursor movement, line wraps, and overwritten characters.

This means:
- A `\r` (carriage return) followed by new text overwrites the line in-place. `capture-pane` returns only the final rendered line, not the intermediate states.
- Progress bars, spinners, and other CR-based animations collapse to their last state.
- Escape sequences that moved the cursor, cleared regions, or changed attributes are already applied. The output is the result, not the instructions.

### Flags Used by TeleClaude

| Flag | Behavior |
|------|----------|
| `-p` | Print captured content to stdout instead of a tmux paste buffer. Required for programmatic use. |
| `-e` | Include ANSI escape sequences for text attributes (color, bold, underline, etc.) and background attributes. Without `-e`, the output is plain text with no styling information. |
| `-J` | Join wrapped lines and preserve trailing spaces. When a long line wraps across multiple terminal rows, `-J` rejoins them into a single logical line. Implies `-T` (ignore trailing positions that never had content). |
| `-S N` | Start capture at line N. Zero is the first line of the **visible** pane. Negative values index into scrollback history (e.g., `-S -500` starts 500 lines before the current bottom of visible content). The special value `-` means "start of history." |
| `-E N` | End capture at line N. Same numbering as `-S`. The special value `-` means "end of visible pane." Default captures only visible content. |

### Line Numbering

```
  History (scrollback buffer)
  ┌──────────────────────────┐
  │ line -N   (oldest)       │  ← -S -N starts here
  │ line -(N-1)              │
  │ ...                      │
  │ line -1                  │
  ├──────────────────────────┤
  Visible pane
  │ line 0    (top)          │  ← -S 0 (default start)
  │ line 1                   │
  │ ...                      │
  │ line H-1  (bottom)       │  ← -E default (end of visible)
  └──────────────────────────┘
```

- Line 0 is always the first line of the visible pane area.
- Negative numbers count backwards into scrollback history.
- `-S -` means the absolute start of the scrollback buffer.
- `-E -` means the absolute end of the visible pane.

### Character Encoding

- tmux detects UTF-8 support from `LC_ALL`, `LC_CTYPE`, and `LANG` environment variables.
- When UTF-8 is supported, `capture-pane` output contains UTF-8 encoded text.
- When UTF-8 is not available, multi-byte characters are replaced with underscores.
- The `-C` flag (not used by TeleClaude) escapes non-printable characters as octal `\xxx`.

### Rendered State vs Raw Byte Stream

This distinction is critical for understanding what `capture-pane` returns:

| Aspect | capture-pane (rendered) | pipe-pane / control mode (raw) |
|--------|------------------------|-------------------------------|
| CR overwrites | Collapsed to final state | Every `\r` + overwrite visible |
| Cursor movement | Applied, not visible | Escape sequences present |
| Colors/attributes | Optionally included via `-e` | Raw escape sequences |
| Scrollback | Accessible via `-S`/`-E` | Not available (prospective only) |
| Wrapped lines | Optionally joined via `-J` | Raw line breaks |
| Content | What a human would see on screen | What the application wrote to the PTY |

## pipe-pane

### Core Behavior

`pipe-pane` (alias `pipep`) connects a pane's output stream to an external command's stdin. It operates on the **raw byte stream** from the application — the same bytes the application writes to its PTY, before tmux's terminal emulator processes them.

### Prospective Attachment (Critical)

`pipe-pane` is strictly **prospective**: it captures only output produced **after** the pipe is established. It does **not** replay scrollback history or already-rendered content. The tmux wiki states it pipes "any new changes to a pane."

This means:
- If an agent has already printed 500 lines before `pipe-pane` is attached, those lines are not available through the pipe.
- To capture historical content, `capture-pane` with `-S`/`-E` must be used instead.
- There is no way to "backfill" a pipe-pane stream with historical data.

### The `-o` Flag

`-o` opens a new pipe only if no previous pipe exists for the pane. If a pipe is already active, `-o` closes it instead. This creates a toggle behavior useful for key bindings but can cause silent failure if code assumes `-o` always starts a pipe.

### What Bytes Flow Through

The pipe receives the raw PTY output stream. This includes:

- **Command echo**: When `send-keys` injects text, the shell echoes it back through the PTY. The pipe sees both the echo and any command output.
- **Prompt redraws**: Shell prompt strings (PS1), right prompts, and completion redraws appear in the stream.
- **ANSI escape sequences**: Color codes, cursor movement, screen clearing, title setting — all present as raw escape bytes.
- **Bracketed paste toggles**: `\x1b[?2004h` (enable) and `\x1b[?2004l` (disable) sequences from applications that use bracketed paste mode.
- **CR in-place updates**: Progress bars and spinners emit `\r` followed by updated text. Each intermediate state appears in the pipe (unlike `capture-pane` which shows only the final state).
- **Newlines**: Applications typically write `\n` but the terminal driver may translate to `\r\n` depending on PTY settings.

### Pane Exclusivity

A pane may only be connected to one pipe command at a time. Starting a new `pipe-pane` closes any existing pipe before launching the new command.

### Lifecycle

1. **Start**: `pipe-pane -o -t <session> '<command>'` — spawns command, connects pane output to its stdin.
2. **Running**: All new PTY output is written to the pipe command's stdin.
3. **Stop**: `pipe-pane -t <session>` (no command) — closes the pipe.
4. **Session death**: If the tmux session is killed, the pipe command's stdin gets EOF and it terminates.
5. **Command death**: If the pipe command exits or crashes, tmux notices on the next write attempt and cleans up the pipe.

### Session Reconnect Behavior

`pipe-pane` state is per-pane, managed by the tmux server process. It is **independent of client attachment**:
- Detaching and reattaching a client does not affect an active pipe.
- The pipe continues operating whether zero, one, or many clients are attached.
- The pipe is tied to the pane's lifetime, not the client's.

## Session Model

### Persistence

tmux sessions are managed by a long-running server process. Sessions survive:
- Client detachment (`C-b d` or network disconnect)
- SSH session termination
- Terminal emulator closure

Sessions are destroyed only by:
- Explicit `kill-session` command
- Last window in the session closing (unless `remain-on-exit` is set)
- `destroy-unattached` option (if enabled)
- tmux server shutdown

### Pane State Persistence

Each pane maintains:
- A scrollback history buffer (size controlled by `history-limit`, default 2000 lines)
- Current terminal emulator state (cursor position, attributes, alternate screen)
- Environment variables (set via `set-environment` or `-e` on `new-session`)
- The running process tree (shell and its children)

All of this persists across client detach/reattach cycles.

### Health Checking

**`has-session -t <name>`**: Returns exit code 0 if the session exists, 1 if it does not. Cheapest existence check.

**`list-panes -t <session> -F <format>`**: Returns pane metadata. Key format variables:

| Variable | Description |
|----------|-------------|
| `#{pane_dead}` | `1` if the pane's process has exited, `0` otherwise |
| `#{pane_id}` | Unique pane identifier (e.g., `%0`, `%1`) |
| `#{pane_pid}` | PID of the pane's initial process (the shell) |
| `#{pane_current_command}` | Name of the foreground process in the pane |
| `#{pane_tty}` | Pseudo-terminal device path |

**`display-message -p -t <session> <format>`**: Prints a single formatted string to stdout. Used for targeted variable queries.

## Sources

- [tmux(1) man page — OpenBSD](https://man.openbsd.org/tmux.1)
- [tmux Wiki — Advanced Use](https://github.com/tmux/tmux/wiki/Advanced-Use)
- [tmux Wiki — Getting Started](https://github.com/tmux/tmux/wiki/Getting-Started)
- [tmux Wiki — Control Mode](https://github.com/tmux/tmux/wiki/Control-Mode)
- [tmux source repository](https://github.com/tmux/tmux)

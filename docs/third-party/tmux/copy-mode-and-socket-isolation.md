---
description: tmux copy-mode input routing, the pane_in_mode format variable, send-keys -X cancel, and TMUX_TMPDIR socket isolation
---

# tmux Copy-Mode and Socket Isolation

## Purpose

Document the tmux behaviors that govern input injection into a pane that is in
copy-mode, and the socket-isolation mechanism used to drive the real
`teleclaude/core/tmux_bridge/_keys.py` primitives against a throwaway tmux server
in tests. Focused on the subset used by the send-keys paste/submit pipeline and
its copy-mode guard.

## Copy-mode and key routing

A pane enters **copy-mode** when the operator scrolls up (`copy-mode`, or the
default `PageUp` binding `copy-mode -eu`) or invokes any command that pushes the
pane into a mode. While a pane is in a mode, tmux interprets incoming key input
against the **mode's key table** (the `copy-mode` / `copy-mode-vi` table), not
the pane's foreground program. A discrete `Enter` / `C-m` sent with `send-keys`
while the pane is in copy-mode is therefore consumed by the mode's key table
(where `Enter` is bound to `copy-selection-and-cancel` or similar) and never
reaches the foreground program as a line submit.

Consequence for input injection: pasting a buffer and then sending a discrete
submit keystroke does not submit when the target pane starts in copy-mode — the
submit key is eaten by the mode. The pane must be returned to its live state
before the submit is sent.

## `pane_in_mode` format variable

`#{pane_in_mode}` expands to the **number of modes the pane is in** (`man tmux`,
FORMATS). It is `0` when the pane is live (no mode) and non-zero when the pane is
in a mode such as copy-mode. tmux's own conditional format `#{?pane_in_mode,…,…}`
treats the value as boolean — non-zero is true. A guard that decides "is this
pane in a mode?" tests for a non-zero value, not strictly `1`.

Query it without attaching a client:

```
tmux display-message -p -t <target> '#{pane_in_mode}'
```

## `send-keys -X cancel`

`send-keys -X <command>` dispatches a **copy-mode command** into the pane's mode
rather than sending literal keys (`man tmux`, `send-keys [-FHKlMRX]`). The
`cancel` copy-mode command (default binding vi `q` / emacs `Escape`) exits the
mode and returns the pane to its live state:

```
tmux send-keys -t <target> -X cancel
```

Issuing `-X cancel` only makes sense while the pane is in a mode; on a live pane
there is no mode to cancel. Guard it behind a `pane_in_mode` check so it is a
no-op for live panes.

## `TMUX_TMPDIR` socket isolation

tmux stores its server socket in a directory `tmux-UID` under `$TMUX_TMPDIR`
(falling back to `/tmp` when unset); the default socket is named `default`
(`man tmux`, `-L` option and ENVIRONMENT). Setting `TMUX_TMPDIR` to a fresh,
private directory therefore relocates the **default** socket into that directory,
yielding a fully independent tmux server without passing `-L <socket>` or
`-S <path>` on any command line.

This matters for tests that must exercise the real bridge: the production
primitives in `_keys.py` shell out as `[config.computer.tmux_binary, <subcommand>,
…]` with no socket flag, so they always target the _default_ socket. A test that
starts its throwaway server via `-L <socket>` would place the pane on a socket the
real bridge never talks to. Isolating via `TMUX_TMPDIR` instead — set in the
process environment before both the test's own tmux setup commands and the bridge
subprocesses run — routes both to the same private default socket, so the real
bridge reaches the isolated pane. The isolated server is torn down with
`tmux kill-server` (it resolves the same default socket from the environment).

### `$TMUX` overrides the relocated default socket

When a process already runs **inside** a tmux pane, tmux exports `TMUX` into the
environment as `<socket-path>,<server-pid>,<session-id>` — the absolute path of
the server it belongs to. A tmux client command that passes no `-L`/`-S` uses the
socket named in `$TMUX` when it is set, **in preference to** the `TMUX_TMPDIR`
default-socket path. So under `TMUX_TMPDIR` isolation, an inherited `$TMUX` sends
the bridge's socket-flag-less commands to the _outer_ live server rather than the
isolated one — with no isolation at all, and, for input injection, keystrokes
delivered into the outer pane. `TMUX_TMPDIR` isolation is therefore only hermetic
when `$TMUX` is also cleared from the environment (`del os.environ["TMUX"]`)
before any tmux command runs. The `-L`/`-S` harness in
`tests/process/test_pane_theming.py` sidesteps this because an explicit socket
flag overrides `$TMUX`; a `TMUX_TMPDIR`-only harness must clear `$TMUX` itself.

## Sources

- [tmux(1) man page — OpenBSD](https://man.openbsd.org/tmux.1)
- [tmux Wiki — Advanced Use](https://github.com/tmux/tmux/wiki/Advanced-Use)

The tmux(1) man page is authoritative for the semantics cited above: FORMATS
(`pane_in_mode`), `send-keys` `-X` command dispatch, the copy-mode `cancel`
command, the `-L` option, and the ENVIRONMENT section (`TMUX_TMPDIR`).

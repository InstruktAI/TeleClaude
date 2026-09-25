---
visibility: public
number: 0101
date: 2026-09-25
description: A local client authorizes its caller in its own process and carries the resolved identity; the daemon neither verifies nor authorizes a local caller.
---

# Clients Authorize and the Daemon Trusts Carried Identity — ADR

## Context

Every `telec` command that asked the daemon to act sent identity signals — a
session id read from the session's identity document, a session token, the
terminal login's email, and the tmux session name — and the daemon re-verified
them on every request: it loaded the session, compared the tmux name, validated
the token against its ledger, resolved the terminal email, and applied the
command's role band before acting. The CLI's local commands resolved their
caller a second way, in process.

Two implementations of "who is calling and what may they do" drifted apart: the
local documentation gate and the daemon answered the same session differently
within seconds. The daemon round trip also sat in front of commands that need
no live process to authorize. Every agent process runs as the same operating
system user as the daemon, so the daemon's check protected nothing a process
running as that user could not reach directly.

An earlier decision made a session's principal resolve from its session record,
reached through the session id its identity document names, and made the CLI
and the daemon share that principal resolution. Identity is established once,
at the boundary a human crosses — the terminal login, or the session a verified
identity starts — and carried by everything inside it.

## Decision

A local client authorizes its caller in its own process, before it sends any
request: the CLI clears a command against that command's role band, and the TUI
clears each of its own actions. The client carries the identity it resolved on
the request. The daemon takes the carried identity as given — it performs no
session lookup to confirm it, no tmux comparison, no token validation, and no
role-band clearance of a local caller — and it records who asked from that
identity. The rules that scope an act to the objects it touches (a session acts
on no session above it, reminders belong to their session, a claimed todo is
written only by its claiming group) stay with the daemon, which evaluates them
against the carried session.

## Consequences

- One implementation decides clearance for every local caller; the daemon and
  the CLI can no longer disagree about a caller.
- A command is refused before any request is sent, so an unidentified or
  out-of-band caller never reaches the daemon.
- The daemon's request surface is no isolation boundary between local
  processes. A process that bypasses the CLI and writes to the socket directly
  is performed as whatever identity it carries. This was already true of any
  process running as the daemon's user, which can read the session store and
  every credential the daemon holds.
- The session token and the tmux name stop being credentials. Tokens that are
  still issued authenticate nothing.
- Person-bound service access selects its person from the carried identity; the
  client's resolution, not a daemon re-check, is what binds a request to a
  person.
- A client that has not been taught to clear an action performs it unchecked;
  every client path that asks the daemon to act must clear before sending.

## Alternatives Considered

- **Keep daemon-side verification and clearance.** Rejected: it keeps the second
  implementation whose drift caused the failures, and the round trip, while
  adding no protection against a process running as the daemon's user.
- **Verify locally with the tmux cross-check, or attest the socket peer's
  process.** Rejected: a verified identity is carried forward, not re-verified
  at every hop; an in-session re-check re-resolves what the session already
  carries. Operating-system peer attestation over the socket was previously
  withdrawn for the same reason.
- **Let the CLI authorize but keep daemon clearance for the TUI and other API
  clients.** Rejected: the daemon cannot tell a CLI request from any other local
  request, so keeping its clearance for some clients keeps the second
  implementation for all of them.

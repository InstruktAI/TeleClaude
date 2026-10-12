---
visibility: internal
number: 0121
date: 2026-10-12
description: An API request addressed to another computer is carried whole to that computer as one relay command at the API boundary, instead of each route opting into its own forwarding.
---

# Computer-Addressed Requests Cross as One Relay Command — ADR

## Context

The daemon reaches another computer through two opt-in sets. A route forwards
a write only if it builds one of the internal command types the dispatcher
knows; a route answers a read from another computer only if the read is one of
a closed list of relayable reads. Both sets were populated for sessions and
then stopped growing. On 2026-10-12 the API served 90 routes; 7 writes and 7
reads could reach another computer, all about sessions, operations and history.
Every todo, artifact, reminder, job, agent-status, settings, memory and MCP
route ran only against the local computer, and the command-classification
design listed todo command types that had never been built.

The clients compounded the gap. The TUI shows every computer's projects and
todos from the daemon's cache and offers the same actions on all of them, but
only the sessions view sends the row's computer; the preparation view sends a
remote todo's identity and project path to the local daemon, which cannot
resolve them and answers with a technical error that the work-feedback boundary
records without a toast. The artifact viewer opens the local todo store
directly. Twelve `telec` commands accept a computer; none of the todo, artifact,
bug or job commands do.

The failure is structural: participation in cross-computer execution is a
per-route decision, so every route added without it silently runs on the wrong
computer, and nothing in the system notices.

## Decision

The API boundary owns the one crossing. Before any route runs, the boundary
reads the computer a request names. A request naming this computer, or none,
runs here. A request naming another computer is carried whole — method, path,
query, body and the resolved caller provenance — to that computer as one relay
command, dispatched and forwarded exactly like every other internal command.
The owning computer's boundary reconstructs the request, resolves the relayed
principal's roles from its own registries as every relayed act already does,
runs it through its own route, and the route's complete response crosses back
unchanged: status, body, receipt or work feedback. Nothing is authenticated
again on the owning computer.

Routes therefore run only against local state and hold no remote path of their
own. The command remains the only wire format; the relay command is one more
command, not a second vocabulary. Every daemon-backed `telec` command that acts
on an object a computer owns accepts the computer to address, and every TUI
row carries the computer it belongs to.

## Alternatives Considered

- **One internal command type per route.** Matches the design's earlier letter
  and keeps the per-command handler table as the funnel. Rejected: it needs
  some thirty-five new command types plus a clearance verb for each, and it
  stays opt-in — the exact property that produced the gap.
- **Relaying the CLI's argument vector to the other computer.** Trivially
  covers every command. Rejected: it is the command-string vocabulary the
  command-classification design forbids, re-parsed by the peer and cleared
  nowhere.
- **Refusing remote rows in the clients.** A notice that the action must be
  performed on the owning computer. Rejected: it makes the hole visible without
  closing it, and leaves every daemon-backed command single-computer.

## Consequences

- A newly added route is remote-capable without any action by its author, and a
  route cannot be added without it.
- A read addressed to another computer returns that computer's live answer
  rather than a cached projection, so it depends on that computer being
  reachable and answers more slowly than the cache.
- Authentication stays at the edge and the person band stays with the owner,
  unchanged from the existing cross-computer authorization contract; the relay
  widens which requests that contract covers, not how it decides.
- A receipt that crosses back names the owning computer; clients follow and
  read the operation there.
- A computer running a version without the relay refuses the relay command by
  capability, so a mixed-version fleet fails loudly, naming the computer, rather
  than executing locally in its place.
- The session routes' own per-command forwarding and the closed relayable-read
  list become redundant for API-originated requests; adapter-originated commands
  keep forwarding through the dispatcher as before.

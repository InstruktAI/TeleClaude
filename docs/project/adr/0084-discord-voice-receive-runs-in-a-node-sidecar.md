---
description: Discord voice reception runs in a Node sidecar behind a custom Gateway adapter, because no released Python library receives encrypted Discord voice safely.
date: 2026-09-11
number: 84
---

# Discord Voice Receive Runs in a Node Sidecar — ADR

## Context

TeleClaude needs two-way audio in a private Discord voice room: speech from one
person becomes agent input, and that agent's reply is spoken back. The platform
already owns a Discord Gateway client in Python, and every other Discord
capability runs through it.

Discord's voice media path is encrypted, and reception is not documented as a
supported public bot capability. Any solution therefore depends on a library
that implements an undocumented protocol surface, including its key transition
and recovery behaviour. That places the choice at a security boundary: a wrong
dependency here means decrypting audio incorrectly, or handling keys in code
nobody else exercises.

The platform's Python Discord library sends voice with its optional extras and
can join a room and stream audio. It provides no maintained live receive.

## Decision

Keep the Gateway in Python and run Discord voice reception in a Node sidecar,
using the released Node voice library through its custom adapter interface. The
Python client continues to own the Gateway connection and executes voice-state
changes through the library's public API on the sidecar's request; the sidecar
holds only the voice connection and never receives a long-lived bot token.

Build only the bridge between the two processes. Adopt the encrypted transport,
key transition, and recovery handling from the released library rather than
implementing any of it.

## Alternatives Considered

- **The community receive extension for the Python library.** Its encrypted
  receive work is unmerged and marked unstable by its own authors. Source
  inspection found paths where a failed decrypt can still reach the decoder,
  and where loss concealment can inspect a packet before decryption. A known
  fork retains related concerns. Rejected: adopting unreviewed cryptographic
  handling is the specific risk this decision exists to avoid.
- **An alternative Python fork of the Discord library.** Its documentation
  warns that encrypted recording may fail, and it had no released receive
  support. Rejected: replacing the Gateway library is a large migration that
  buys no working receive.
- **Implement receive in Python directly.** Rejected: this reimplements
  encrypted media transport and key management — the security boundary above —
  with no released implementation to check against.
- **Do not offer voice reception.** Rejected: it is the capability being
  sought, and a live proof showed the adopted path works end to end.

## Consequences

- A second language runtime enters the deployment for this capability. The
  sidecar is a process boundary, so its failure degrades voice alone and leaves
  text conversation untouched.
- Two processes must agree on lifecycle. Join and disconnect decisions stay
  with the Python side so a sidecar restart cannot re-establish a connection on
  its own authority, and readiness is bounded rather than awaited indefinitely.
- The capability inherits the provider caveat. Because reception is
  undocumented, provider changes may break it without notice, and the transport
  is built to fail closed and visibly rather than degrade into guessed input.
- The credential boundary stays where it already is. The sidecar receives only
  what one voice session requires.
- A comparable deployed architecture — a Discord-to-telephony bridge doing
  two-way audio with per-user allowlisting — supports the feasibility of this
  shape without removing the caveat.

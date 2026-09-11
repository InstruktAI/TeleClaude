---
description: Two-process Discord voice transport — Python owns the Gateway, a Node sidecar owns the encrypted voice connection — with explicit utterance closure, single-owner connection claim, and fail-closed identity.
delivered_by:
  - discord-personal-voice-conversation
---

# Discord Voice Transport — Design

## Purpose

Carry live audio in and out of one person's private Discord voice room so a
TeleClaude session can be spoken to and heard, without moving Discord protocol
knowledge out of the integration boundary.

The transport exists because no single library covers the need. The platform's
Discord client sends voice but does not receive it; the released library that
receives voice runs on another runtime. This design splits the two
responsibilities across processes while keeping exactly one owner of the
Gateway connection and exactly one owner of the voice connection.

### Prior art & adopt-vs-build

Surveyed before choosing a dependency:

- **The platform's current Discord library** sends voice with its optional
  extras and proved able to join the target room and stream speech, but
  provides no maintained live receive.
- **The community receive extension** has unmerged encrypted-receive work that
  its own authors mark unstable; source inspection found paths where a failed
  decrypt can still reach the decoder and where loss-concealment can inspect a
  packet before decryption. A known fork retains related concerns. Neither is
  adopted.
- **An alternative Python fork** documents that encrypted recording may fail and
  had no released receive support during investigation; replacing the Gateway
  library would widen scope without supplying a solution.
- **The released Node voice library** supports encrypted send and receive,
  exposes a custom adapter interface that lets another process own the Gateway,
  and handles key transition and recovery. Its documentation states receive is
  not guaranteed stable, for the same provider reason above.
- **Comparable production architecture:** a deployed Discord-to-telephony
  bridge performs two-way audio with per-user allowlisting, supporting
  feasibility without removing the provider caveat.

**Decision: adopt the released Node voice library behind a sidecar, and build
only the bridge.** A live two-process proof joined the room, streamed speech,
and received clean encrypted audio that the existing transcription backend
transcribed correctly, splitting two real transmissions at their explicit
closure markers. Building a receive stack in Python was rejected: it would
reimplement encrypted transport and key handling — a security boundary — with
no released implementation to adopt.

## Inputs/Outputs

**Inputs:**

- Voice-state and voice-server events from the existing Discord Gateway client.
- The person-scoped voice configuration: bot token, voice channel, and the
  computer declared to own the connection.
- Rendered audio artifacts produced by the TTS render contract.

**Outputs:**

- Closed utterance recordings handed to the established voice-input workflow.
- Playback into the voice room.
- Voice-room presence and connection lifecycle signals.

## Invariants

1. **Python owns the Gateway; the sidecar owns only the voice connection.** The
   sidecar never holds a long-lived bot token and never opens a Gateway
   connection of its own. It requests voice-state changes; the Python client
   executes them through the library's public voice-state API.
2. **One owner per bot identity per guild.** The computer named by the person's
   voice configuration owns the connection. A peer that receives the same
   provider event performs no voice side effect — no join, move, receive, or
   playback. This extends the fleet rule in
   `project/spec/feature/integration/discord-interaction-ownership` to a
   resource with no forum ancestry to derive ownership from.
3. **Only explicit transmission-end framing closes an utterance.** Silence,
   voice-activity detection, inferred speaking state, and elapsed time never
   close or submit. A transmission whose closure is missing or structurally
   incomplete yields no agent input and its recording is discarded through an
   explicit lifecycle transition.
4. **An utterance is latched to the session focused when it began.** A focus
   change during capture, transcription, or delivery never redirects it.
5. **Only the configured person is received.** Audio from any other speaker in
   the room is discarded at the transport boundary and never becomes agent
   input.
6. **Identity fails closed.** Person, Discord user, channel, bot identity, and
   session are resolved before any capture or playback. An unresolved or
   ambiguous mapping starts nothing. A room's name is presentation and
   identifies nobody.
7. **Secrets and payloads stay out of logs.** Bot tokens, voice-server tokens,
   session keys, decrypted audio, and transcription bodies are never logged at
   routine levels.
8. **Recordings are bounded and private.** Temporary recordings carry restricted
   permissions and a bounded lifecycle; cancellation removes them.

## Primary flows

```mermaid
sequenceDiagram
    participant D as Discord
    participant P as Python adapter (Gateway owner)
    participant N as Node voice sidecar
    participant C as Core voice-input workflow

    D->>P: voice state update (person joins room)
    P->>P: resolve person, channel, owner; refuse if foreign
    P->>N: open voice session (adapter handshake)
    N->>P: request voice-state change
    P->>D: change voice state (public API)
    D-->>N: voice server / encrypted media
    N->>N: receive, decrypt, decode; split at explicit closure
    N->>P: closed utterance recording
    P->>C: hand off closed utterance
    C->>C: transcribe, deliver once to latched session
```

Playback reverses the path: a rendered audio artifact is handed to the sidecar,
which streams it into the room. Switching focus or leaving the room stops
current playback and drops queued speech for the previous selection.

**Failure propagation is bidirectional and bounded.** Either side may report
that the voice session ended; both then release their state. Readiness is
bounded rather than awaited indefinitely. Only one side decides to join and
disconnect — the Python adapter — so a sidecar restart never re-establishes a
connection on its own authority.

## Failure modes

- **Reception is not a documented public capability.** Discord does not
  document bot voice reception as a supported API, so provider behaviour may
  change without notice. The transport fails closed and visibly rather than
  degrading into inferred submission.
- **Missing, partial, or ambiguous closure framing** — no submission. Observed
  framing counts from investigation are observations, not constants; the
  transport reads explicit framing semantics and retains sequencing
  information rather than counting frames.
- **Packet loss, reordering, and mid-call key rotation** — unverified at design
  time. Each resolves to no submission rather than to a guess.
- **Sidecar unavailable or crashed** — the voice room is simply unavailable;
  text conversation is unaffected.
- **Bot identity divergence** — where the configured voice token authenticates
  a different bot from the one the Discord adapter already runs,
  configuration fails rather than operating two identities.
- **Playback bleeding into capture** — the bot's own speech must never be
  received as the person's input; full duplex is verified before it is claimed.

## See Also

- docs/project/spec/feature/integration/discord-personal-voice-conversation.md
- docs/project/spec/feature/integration/discord-interaction-ownership.md
- docs/project/design/architecture/tts-system.md
- docs/project/spec/domain/integration.md

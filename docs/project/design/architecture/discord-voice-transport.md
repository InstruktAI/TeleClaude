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
3. **The sender's stop sequence is the push-to-talk release.** A Discord client
   emits a run of Opus silence frames immediately before it stops sending. Under
   push-to-talk the held key is the transmission: the client encodes and sends
   throughout it, silence included, so it stops sending exactly once — at
   release. The run is therefore a positive, receiver-visible release marker.
   The evidence for this on the target client is recorded at
   `@input#live-evidence-already-established`.
4. **The closure rule is executable and counts nothing.** Packets are ordered by
   their transport sequence. A run of consecutive stop frames closes the
   utterance at the first frame of the run; the audio before it is the
   utterance. Recognition is by consecutive identical frames, not by a fixed
   count — the number observed in one session is an observation, never a
   constant. An incomplete run at the end of received data, or a run that
   cannot be ordered, closes nothing: nothing is submitted and the recording is
   discarded through an explicit lifecycle transition.
5. **Every other closure mechanism is refused.** Silence detection,
   voice-activity detection, elapsed time, and inferred speaking state never
   close or submit. The receive library's timeout-derived speaking-end event
   and its silence- and inactivity-based stream-end modes are specifically not
   used; the transport reads raw packets and applies the rule above. A
   speaking-state update carrying a zero mode is not a documented stop signal
   and is not relied upon.
6. **Conditions not yet exercised are verified before delivery, not designed
   around.** Packet loss, reordering, discontinuous-transmission settings,
   mobile clients, and an in-call key rotation are listed in
   `@input#verification-required-before-delivery` and are the plan's
   verification tasks. Each is exercised against the rule above; the rule is
   not weakened in anticipation of them.
7. **An utterance is latched to the session focused when it began.** A focus
   change during capture, transcription, or delivery never redirects it.
8. **Only the configured person is received.** Audio from any other speaker in
   the room is discarded at the transport boundary and never becomes agent
   input.
9. **Identity fails closed.** Person, Discord user, channel, bot identity, and
   session are resolved before any capture or playback. An unresolved or
   ambiguous mapping starts nothing. A room's name is presentation and
   identifies nobody.
10. **Secrets and payloads stay out of logs.** Bot tokens, voice-server tokens,
    session keys, decrypted audio, and transcription bodies are never logged at
    routine levels.
11. **Recordings are bounded and private.** Temporary recordings carry restricted
    permissions and a bounded lifecycle; cancellation removes them. Artifact
    paths are canonicalized and confined to a private root; a path escaping that
    root is refused rather than normalized.

### The bridge channel

12. **The channel is private by construction, not by permission.** The parent
    creates a connected stream pair before spawning the sidecar and the child
    inherits its end. The bridge has no filesystem rendezvous, no listening
    endpoint, and no network port, so no other local process can reach it and no
    peer authentication step is required to establish who is on the other end.
13. **Messages are typed and versioned, and validation is total.** Every message
    declares a type and a protocol version from a closed vocabulary. An unknown
    type, an incompatible version, or a structurally invalid payload is rejected
    and recorded — never partially applied and never ignored. Raw provider
    payloads are normalized at the boundary and never forwarded verbatim.
14. **Every message carries its voice-session generation.** The parent assigns a
    generation when it opens a voice session. A message bearing any other
    generation is stale and is rejected, so a restarted sidecar or a late
    in-flight message cannot act on a connection that has since been replaced.
15. **The sidecar receives only what one voice session needs.** Ephemeral
    per-session voice credentials travel on the bridge; the long-lived bot token
    never does and is never present in the child's environment or arguments.
16. **The parent owns the process lifecycle.** Spawn, bounded readiness,
    shutdown, and restart are the parent's decisions. The sidecar never
    re-establishes a voice connection on its own authority, and a child that
    exits leaves the parent to decide whether a replacement is opened.

### Reaching a session on another computer

17. **Focus derivation needs no new publication.** The cluster session snapshot
    already carries the identified human and the time their input was last
    accepted, which is exactly what the focus rule orders on. The voice-owning
    computer derives focus from snapshots it already receives.
18. **One additive query carries the spoken reply.** A session's complete
    user-visible final response is not in the published snapshot, which carries
    the generated summary and an output digest. A request for that full output
    and its version is added to the cross-computer request vocabulary as a new
    entry; existing entries and payloads are unchanged, and readers tolerate
    fields they do not know.
19. **A peer that lacks the query degrades rather than fails.** The fleet runs
    mixed versions, so an unknown-request answer from an older peer means the
    reply for that session is not spoken and the reason is visible. It never
    stalls the room, and it never falls back to speaking the summary, which is
    not the approved outcome.
20. **The final-output version is what identifies a reply, and it is published
    additively.** The session's output-stop marker is the version; the existing
    `last_output_digest` is not. That digest is internal dedupe state for output
    routing — digest-only writes deliberately emit no session-updated event, so a
    remote snapshot can retain a stale value, and equal text at two versions
    yields one digest. The snapshot therefore gains the output-stop version as an
    additive field, and the full-output query returns the same version alongside
    the text. Re-hearing an unchanged reply is settled against that version
    before any cross-computer request is made; adapter delivery state never
    stands in for a domain version.
21. **Delivery and cancellation use what exists.** A latched utterance reaches a
    remote session through the established cross-computer session-input path.
    Cancellation is local to the voice-owning computer, which owns the playback
    queue, and needs no fleet contract.

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
- **Missing, partial, or unorderable stop sequence** — no submission, and the
  recording is discarded.
- **Packet loss, reordering, and mid-call key rotation** — ordering is applied
  before the closure rule; a case the rule cannot resolve produces no
  submission rather than a guess.
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
- docs/project/adr/0084-discord-voice-receive-runs-in-a-node-sidecar.md

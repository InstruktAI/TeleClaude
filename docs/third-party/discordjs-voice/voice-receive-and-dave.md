---
description: '@discordjs/voice 0.19.2 — encrypted (DAVE) send and receive over a custom Gateway adapter: dependency set, engine requirement, receive-side end signals, and the documented stability caveat.'
---

# @discordjs/voice — Voice receive, DAVE, and the custom adapter

## Verified facts

- **Version pinned by this project:** `0.19.2`.
- **Runtime dependencies (exact set at 0.19.2):** `@snazzah/davey ^0.1.9`
  (DAVE end-to-end encryption; `0.1.12` resolves at the time of writing),
  `prism-media ^1.3.5`, `discord-api-types ^0.38.41`, `ws ^8.19.0`,
  `tslib ^2.8.1`, `@types/ws ^8.18.1`. No peer or optional dependencies are
  declared.
- **Opus is not a dependency.** The library expects the host to supply an Opus
  encoder/decoder. `@discordjs/opus` appears only in its devDependencies. A pure
  JavaScript alternative, `opusscript` (`0.1.1` at the time of writing), avoids
  a native build.
- **Engine:** Node `>=22.12.0`.
- **Custom adapter:** a `DiscordGatewayAdapterCreator` lets another process own
  the Gateway. The adapter receives `VOICE_STATE_UPDATE` and
  `VOICE_SERVER_UPDATE` payloads from the owner and sends opcode-4 voice-state
  requests back through `sendPayload`. The library never needs the bot token
  when driven this way; it needs the per-session voice token carried in
  `VOICE_SERVER_UPDATE`.
- **Receive API:** `VoiceConnection.receiver` exposes per-SSRC Opus packet
  streams (`subscribe(userId, { end })`). The public speaking-end signal
  (`receiver.speaking.on('end')`) is emitted after a fixed packet-inactivity
  timeout; the subscription `end` behaviours are `Manual`, `AfterSilence`, and
  `AfterInactivity`. None of these is a sender-emitted stop signal. The
  subscribed stream pushes decrypted Opus frames only: the RTP header is parsed
  and removed before the push, and neither sequence nor timestamp is exposed on
  the stream. The unencrypted transport header remains observable one layer
  down — `Networking` and `VoiceUDPSocket` are public exports, and the UDP
  socket emits each raw received datagram as a `message` event before
  decryption.
- **Stability caveat (upstream wording):** receiving audio is not guaranteed to
  be stable, because Discord does not document bot voice reception as a
  supported public API.

## Discord voice protocol facts the library implements

- A client must send at least one Speaking payload (opcode 5) before
  transmitting audio; a zero speaking mode is not permitted for sending, and
  the protocol documents no end-of-transmission payload.
- Before a client stops sending, it emits a short run of Opus silence frames
  (`0xF8 0xFF 0xFE`) so the receiver's decoder does not interpolate into the
  next transmission. The documented purpose is decoder reset before a break in
  sent data.

## Gaps

- No upstream statement covers behaviour under packet loss or reordering at
  the receive boundary, mid-call DAVE key rotation from the receiver's side, or
  mobile-client transmission behaviour. Each remains to be exercised by the
  consuming project.

## Sources

- https://www.npmjs.com/package/@discordjs/voice/v/0.19.2 (registry metadata, dependencies, engines)
- https://discordjs.guide/voice/ (custom adapter and receive guide)
- https://docs.discord.com/developers/topics/voice-connections (Speaking payload; silence frames before stopping)

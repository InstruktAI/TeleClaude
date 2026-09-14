---
description: Personal Discord voice rooms provide push-to-talk agent input, automatic session-voiced replies, and explicit thread selection.
delivered_by:
  - discord-personal-voice-conversation
---

# Discord Personal Voice Conversation — Spec

## What it is

A human can converse aloud with one TeleClaude agent session while remaining in a private Discord voice channel. Entering the configured room brings the voice bot into the call. Push-to-talk speech is transcribed and delivered to the human's selected session; that session's complete reply is rendered with its persistent voice and played into the room automatically.

The selected session follows the human's latest accepted input across sessions. A thread-level `Listen here` control explicitly selects a different session and plays its latest complete reply, so listening can move between agent threads without sending a prompt.

This first delivery supports one configured person using the existing Discord bot identity in one guild. Voice input is push-to-talk only. Discord Activities, automatic voice-channel creation, distinct per-person bot provisioning, and silence-based utterance submission are outside its scope.

### Business value

The human can move between visible agent threads and voice conversation without pre-generating audio, downloading attachments, pressing a second playback control, or risking a silent pause being mistaken for submission.

## Canonical fields

### Conversation contract

- A personal voice room is bound through the identified person, Discord user, configured channel, and authenticated voice bot.
- Entering the room activates voice delivery and joins the bot; leaving disconnects it and cancels incomplete input and pending output for that listener.
- Voice focus identifies exactly one live agent session. An accepted human input updates focus to its session; `Listen here` updates focus without creating agent input.
- An incoming transmission captures the focused session at its start. Later focus changes never redirect an utterance already being transcribed or delivered.
- Discord's explicit transmission-end framing closes a push-to-talk utterance. Silence, voice activity, and elapsed time never authorize submission. Missing or structurally incomplete closure produces no agent input.
- The established voice-input workflow owns transcription, lifecycle feedback, and exactly-once delivery after the Discord transport produces a closed utterance.
- Spoken output renders the complete user-visible final response rather than the separately generated output summary, using the one Discord voice configured for the rendering provider. The session's own per-session voice and the local summary playback are unchanged.
- Discord voice presence is an audio-destination activation signal. It does not enable host-speaker playback or change local chiptunes audio focus.
- Audio cached for replay is identified by session, final-output version, and effective voice. Replaying unchanged output reuses that audio.
- Changing focus or leaving the room stops stale playback and removes queued speech belonging to the previous selection.
- Voice connection ownership is singular for a bot identity within a guild. Fleet peers that do not own the connection never join, move, receive, or play through it.
- Thread controls use generation-specific identity and exact-message registration. A process-wide component handler never claims unrelated Discord messages.

### Use cases

#### UC-DPVC-1

```gherkin
Given a human has a configured private Discord voice room
When the human enters that room
Then the configured voice bot joins automatically
And the room becomes available for that human's agent conversation
When the human leaves
Then the bot disconnects
And incomplete input and pending speech for that listener are cancelled
```

#### UC-DPVC-2

```gherkin
Given an identified human has active agent sessions represented by Discord threads
When input from that human is accepted by one session
Then that session becomes the human's voice focus
And later activity that is not accepted human input does not change the focus
```

#### UC-DPVC-3

```gherkin
Given a human is listening in the configured voice room
And another agent thread exposes its `Listen here` control
When the human activates that control
Then that thread's session becomes the voice focus
And its latest complete reply is generated or retrieved and played without another playback action
And no prompt is sent to the agent
```

#### UC-DPVC-4

```gherkin
Given a human presses push-to-talk while one session has voice focus
When the human speaks, pauses while continuing to hold, speaks again, and releases push-to-talk
Then the held-button pause remains inside one utterance
And explicit transmission-end framing closes the utterance on release
And the complete utterance is transcribed and delivered exactly once to the session captured at transmission start
```

#### UC-DPVC-5

```gherkin
Given received voice data has no complete explicit transmission-end framing
When silence or elapsed time follows the received data
Then no transcription is submitted to an agent
And the incomplete recording is discarded through an explicit lifecycle transition
```

#### UC-DPVC-7

```gherkin
Given the focused session completes a substantive user-visible reply
And its human remains in the configured voice room
When voice output is delivered
Then the complete reply is synthesized with the Discord voice configured for the rendering provider
And it plays automatically through the voice bot
And host-speaker playback and its summary behaviour remain unchanged
```

#### UC-DPVC-8

```gherkin
Given speech from one focused session is playing or queued
When the human selects another session or leaves the voice room
Then stale playback stops
And queued speech for the previous selection does not play
```

#### UC-DPVC-9

```gherkin
Given the daemon restarts while the configured human remains in the personal voice room
When Discord connectivity is restored
Then the owning daemon restores the voice connection and selected-session behavior
And no fleet peer creates a competing voice connection
```

## Known caveats

- Discord message components remain attached to messages and scroll with their thread; Discord provides no fixed thread-footer control for bots.
- Discord documents transmission stop-tail framing but does not guarantee voice reception as a stable public bot API. Missing or ambiguous framing therefore fails without submission rather than falling back to inferred silence.
- One bot identity can maintain only one voice connection per guild. Supporting simultaneous personal rooms in one guild requires distinct bot identities and is a later capability.
- The first delivery requires the configured personal voice bot token to authenticate the same bot identity already owned by the Discord adapter. Separate voice-only bot identities are not provisioned here.

## See Also

- docs/project/spec/feature/integration/discord-interaction-ownership.md
- docs/project/spec/session-output-routing.md
- docs/project/design/architecture/tts-system.md
- docs/project/spec/feature/config/yaml-env-var-expansion.md

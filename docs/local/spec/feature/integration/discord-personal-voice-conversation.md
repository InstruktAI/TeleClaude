---
description: Personal Discord voice rooms provide push-to-talk agent input, automatic
  spoken replies in one configured room voice, and explicit thread selection.
---

# Discord Personal Voice Conversation — Spec

## What it is

A human can converse aloud with one TeleClaude agent session while remaining in their private personal Discord voice channel. Entering that room brings the voice bot into the call. The room is resolved from the identified human's live voice state rather than copied into configuration. Push-to-talk speech is transcribed and delivered to the human's selected session; that session's complete reply is rendered in the one Discord voice configured for the rendering speech service and played into the room automatically.

The selected session follows the human's latest accepted input across sessions. A thread-level `Listen here` control explicitly selects a different session and plays its latest complete reply, so listening can move between agent threads without sending a prompt.

This first delivery supports one configured person using the existing Discord bot identity in one guild. Voice input is push-to-talk only. Discord Activities, automatic voice-channel creation, distinct per-person bot provisioning, and silence-based utterance submission are outside its scope.

### Business value

The human can move between visible agent threads and voice conversation without pre-generating audio, downloading attachments, pressing a second playback control, or risking a silent pause being mistaken for submission.

## Canonical fields

### Conversation contract

- A personal voice room is bound through the identified person, Discord user, their current private voice channel, and their person-scoped authenticated voice bot. The channel is provider state observed from the identified person's voice-state transition, never a configured provider identifier.
- Entering the room activates voice delivery and joins the bot; leaving disconnects it and cancels incomplete input and pending output for that listener.
- Voice focus identifies exactly one live agent session. An accepted human input updates focus to its session; `Listen here` updates focus without creating agent input.
- An incoming transmission captures the focused session at its start. Later focus changes never redirect an utterance already being transcribed or delivered.
- Discord's explicit transmission-end framing closes a push-to-talk utterance. Silence, voice activity, and elapsed time never authorize submission. Missing or structurally incomplete closure produces no agent input.
- The established voice-input workflow owns transcription, lifecycle feedback, and exactly-once delivery after the Discord transport produces a closed utterance.
- Spoken output renders the complete user-visible final response rather than the separately generated output summary, using the one Discord voice configured for the rendering provider. The session's own per-session voice and the local summary playback are unchanged.
- Discord voice presence is an audio-destination activation signal. It does not enable host-speaker playback or change local chiptunes audio focus.
- Audio cached for replay is identified by session, final-output version, rendering service, and voice. Replaying unchanged output reuses that audio.
- Changing focus or leaving the room stops stale playback and removes queued speech belonging to the previous selection.
- Voice connection ownership is singular for a bot identity within a guild. Fleet peers that do not own the connection never join, move, receive, or play through it.
- Thread controls use generation-specific identity and exact-message registration. Each session exposes at most one button-only `Listen here` control: the existing pending-message cleanup lifecycle removes it when the next human input starts, and the completed reply recreates it at the bottom of the thread. A process-wide component handler never claims unrelated Discord messages.

### Use cases

#### UC-DPVC-1: A person can start a voice conversation in their private room

```gherkin
Scenario: Enter and leave a personal voice room
  Given a person has a configured private Discord voice room
  When they enter the room
  Then their assistant is available for voice conversation without manually connecting the bot
  When they leave
  Then incomplete speech and pending replies are cancelled
```

#### UC-DPVC-2: A person's voice conversation follows the assistant they last used

```gherkin
Scenario: Hear replies from the assistant the person last used
  Given a person has several assistant conversations available in Discord
  When they send accepted input to one conversation
  Then spoken replies follow that conversation
  And activity that is not accepted input does not switch the conversation they hear
```

#### UC-DPVC-3: A person can listen to another thread without sending a prompt

```gherkin
Scenario: Listen to another conversation
  Given a person is in the configured voice room and another thread has a Listen here control
  When they choose that thread
  Then they hear its latest complete reply without sending a prompt to the agent
```

#### UC-DPVC-4: A person can pause during push-to-talk without splitting or prematurely sending speech

```gherkin
Scenario: Speak across a pause while holding push-to-talk
  Given a person has selected an assistant conversation
  When they hold push-to-talk, pause while still holding, speak again, and release
  Then one complete utterance reaches the conversation selected when they began speaking

Scenario: Do not submit incomplete speech
  Given a person's voice transmission has no complete ending
  When audio pauses or the connection ends before a complete release
  Then no partial recording reaches the assistant
```

#### UC-DPVC-5

#### UC-DPVC-6

#### UC-DPVC-7: A person hears the complete assistant reply automatically

```gherkin
Scenario: Hear a complete reply in the voice room
  Given a person's assistant completes a user-visible reply while they remain in the voice room
  When the reply is spoken
  Then they hear the complete response automatically in the configured voice
```

#### UC-DPVC-8: A person hears speech only from the conversation they selected

```gherkin
Scenario: Stop speech from the previous conversation
  Given speech from a selected conversation is playing or queued
  When a person selects another conversation or leaves the voice room
  Then speech from the previous conversation stops and no queued reply plays
```

#### UC-DPVC-9: A person can resume voice conversation after the daemon restarts

```gherkin
Scenario: Return to the voice conversation after reconnecting
  Given a person remains in their configured voice room while the adapter reconnects
  When the voice room becomes available again
  Then the assistant conversation follows the person's current selection
```

#### UC-DPVC-10

#### UC-DPVC-11: A person's voice conversation accepts only their own speech

```gherkin
Scenario: Keep another person's speech out of the assistant conversation
  Given a personal voice room is configured for one person
  When someone else in the room speaks
  Then their audio does not reach any assistant conversation
```

## Known caveats

- Discord message components remain attached to messages and scroll with their thread; Discord provides no fixed thread-footer control for bots.
- Discord documents transmission stop-tail framing but does not guarantee voice reception as a stable public bot API. Missing or ambiguous framing therefore fails without submission rather than falling back to inferred silence.
- One bot identity can maintain only one voice connection per guild. Supporting simultaneous personal rooms in one guild requires distinct bot identities and is a later capability.
- The first delivery requires the person overlay's `${DISCORD_TOKEN}` reference to resolve from that person's owner-only environment file and authenticate the same bot identity already owned by the Discord adapter. Missing references fail configuration validation. Separate voice-only bot identities are not provisioned here.

## See Also

- docs/local/spec/feature/integration/discord-interaction-ownership.md
- docs/local/spec/session-output-routing.md
- docs/local/design/architecture/tts-system.md
- docs/local/spec/feature/config/yaml-env-var-expansion.md

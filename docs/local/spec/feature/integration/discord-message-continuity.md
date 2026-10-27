---
description: A person's messages in their Discord session threads and Team channel
  survive a daemon restart. A message that arrives during startup waits for routing,
  and a message posted while TeleClaude was away is recovered from Discord once it
  is back.
visibility: internal
---

# Discord Message Continuity — Spec

## What it is

A person talks to a session through its thread in a project forum or through
their Team channel. A daemon restart does not lose what they post there.

Every window of a restart is covered:

<!-- planned-change:inbound-refused-while-draining-is-dropped -->

- the daemon is stopped;
- the daemon is running but not yet connected to Discord;
- the daemon is connected but its Discord routing is not yet established.

<!-- change:inbound-refused-while-draining-is-dropped -->

- the daemon is draining for a restart and refuses new input;
- the daemon is stopped;
- the daemon is running but not yet connected to Discord;
- the daemon is connected but its Discord routing is not yet established.

<!-- /planned-change:inbound-refused-while-draining-is-dropped -->

A message a person posts in any of these windows, in a place bound to a
still-active session, reaches that session once the daemon is back. It arrives
exactly once, and messages from one place arrive in the order they were posted.

Two rules carry this.

**Startup routing is unknown, not absent.** The daemon's knowledge of which
forums and Team channels it manages is rebuilt at every start. Until that
routing is established, a post is not discarded as unmanaged because the
routing is missing. A post received earlier waits and is classified once
routing is established. The same rule applies to an inconclusive provider
lookup in
`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`:
an unknown is never treated as an absence.

**What the daemon did not receive is recovered from Discord.** Once the daemon
is back, it reads Discord's own copy of every thread and Team channel bound to a
still-active session. Each message a person posted there since the last
message the daemon processed there reaches the session through the same path a
live message takes.
The live path's checks apply unchanged to recovered messages: who may post,
which session the place belongs to, and how voice and file attachments are
handled. A recovered message keeps its original posting time and is identified
as recovered, so the session can tell it was posted while TeleClaude was away.
How that is shown to the agent belongs to
`local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`.

Messages from one place reach the session in the order they were posted. A
message is handed on only once the one posted before it has been accepted, or
its handling has failed for good with the failure reported as it is today. A
text sent right after a voice message therefore waits for that voice message's
transcription.

Messages in channels the daemon does not manage keep their current handling.

### Use cases

#### UC-DMC1: A person's message posted around a restart reaches their session

<!-- planned-change:inbound-refused-while-draining-is-dropped -->

```gherkin
Scenario Outline: A message posted while the daemon restarts
  Given a person has an active session bound to a Discord thread or to their Team channel
  And the daemon is <window>
  When the person posts a message there
  Then once the daemon is back the message reaches that session exactly once
  And the messages posted there reach the session in the order they were posted

  Examples:
    | window                                                 |
    | stopped                                                |
    | running but not yet connected to Discord               |
    | connected but its Discord routing is not yet established |
```

<!-- change:inbound-refused-while-draining-is-dropped -->

```gherkin
Scenario Outline: A message posted while the daemon restarts
  Given a person has an active session bound to a Discord thread or to their Team channel
  And the daemon is <window>
  When the person posts a message there
  Then the person is not asked to send it again
  And once the daemon is back the message reaches that session exactly once
  And the messages posted there reach the session in the order they were posted

  Examples:
    | window                                                   |
    | draining for a restart and refusing new input            |
    | stopped                                                  |
    | running but not yet connected to Discord                 |
    | connected but its Discord routing is not yet established |
```

<!-- /planned-change:inbound-refused-while-draining-is-dropped -->

## Canonical fields

- **Recovery scope:** the threads and Team channels bound to sessions that are
  still active when the daemon is back.
- **Recovery reach:** every message a person posted in such a place since the
  last message the daemon processed there, with no age cutoff.
- **Recovered-message facts:** the original posting time, and the fact that the
  message was recovered rather than received live.

## Known caveats

- A place without a still-active session is not recovered. This includes a
  thread whose session has ended and a new forum post that would start a
  session. A message posted there while the daemon is away is not delivered.
- Recovery reads Discord's copy. A message deleted from Discord before the
  daemon is back is not recovered.
- Before this capability is installed, a place's last processed message is
  known only as far back as the inbound queue retains accepted input. In a place
  with no accepted input inside that window, a message lost in an outage before
  installation and older than the window is not recovered. Whether such a
  message was processed can no longer be told, and recovering it could repeat
  a message the session already received.

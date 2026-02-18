# Session Relay — Output Relay Between Agent Sessions

Daemon-side implementation of the session relay primitive: monitor agent session output via `capture_pane`, deliver delta to all other participant sessions via `send_keys_existing_tmux` with attribution. Baseline snapshot diffing prevents feedback loops.

The relay enables natural agent-to-agent conversation. After a `send_message(direct=true)` handshake, both agents produce output naturally — the daemon handles delivery. No additional tool calls. No wasted tokens. Just a conversation.

## The problem today

`send_message` delivers a message to a session, but there is no automatic relay of the response back. The existing notification system only sends "session finished, go check" metadata — not the actual output content. After the initial message, agents are flying blind. To continue a conversation, they must make tool calls back and forth. Every exchange costs tool-call tokens and breaks the natural flow.

## What this delivers

A bidirectional relay between two agent sessions:

1. Agent A calls `send_message(session_id=B, message="...", direct=true)`
2. The daemon delivers the message to B (existing behavior)
3. The daemon starts a relay: monitor both A and B's output via `capture_pane`
4. B responds naturally — its output is relayed to A with attribution
5. A responds naturally — its output is relayed to B with attribution
6. No further tool calls. The agents just talk.

The receiving agent doesn't need to know about the relay. From its perspective, it received a message and it responds. The response appears in the peer's session. It's just a conversation.

## Design

The relay is a generic N-participant primitive (not hardcoded to 2). This matters because the gathering ceremony (separate todo) will layer turn-managed multi-party communication on top of the same relay. But this todo delivers the 1:1 case only.

Core mechanism:

- A list of participant sessions (2 for 1:1)
- The daemon monitors each participant's output via `capture_pane` at 1-second intervals
- New output (delta beyond baseline) is delivered to all other participants with attribution: `"[Name] ([number]):\n\n[their words]"`
- Baseline resets after each delivery — prevents re-capturing injected content

## Feedback loop prevention

When a message is injected into a session, it becomes part of that session's pane content. The daemon must NOT re-capture injected content as "output." The baseline snapshot mechanism handles this: after each delivery, the baseline includes the injected content. Only new content beyond the baseline is captured.

## Dependencies

- `direct=true` flag on `send_message` / `start_session` (delivered: 6157a769)
- No external dependencies

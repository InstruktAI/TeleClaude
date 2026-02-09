# Bidirectional Agent Links — Requirements

## Problem Statement

Agent-to-agent communication is one-way and mechanical. When Agent A dispatches
work to Agent B, A receives an idle notification when B stops, then must poll B's
transcript via `get_session_data` to understand what B produced. This creates
disengaged orchestrators that process worker output as a bureaucratic chore rather
than cognitive input to reason about.

The root cause is structural: the listener system is one-directional (caller →
target), one-shot (fires once then deregisters), and metadata-only (delivers "B
went idle", not B's actual output).

## Intended Outcome

Agents can communicate directly. When A sends a message to B, both agents' output
flows to the other as conversational input. Each agent feels present in the
exchange. The system prevents infinite loops through anchoring discipline and
turn budget backstops.

## Success Criteria

### SC-1: Bidirectional Output Injection

When Agent A sends a message to Agent B via `send_message`, B's `agent_stop`
output is injected into A's tmux session as input. A's subsequent `agent_stop`
output is injected into B's tmux session. Both directions work.

**Verification**: Start two sessions. A sends message to B. B produces output and
stops. Verify A's tmux session receives B's output as input. A responds and stops.
Verify B's tmux session receives A's output.

### SC-2: Privacy — Only Distilled Output Crosses

Only `agent_stop` output (the final product of a turn) is injected. Thoughts,
tool calls, and intermediate reasoning stay private to the producing agent.

**Verification**: During a linked exchange, verify B's tmux input contains only
B's final output text, not tool call payloads or thinking blocks.

### SC-3: Checkpoint Filtering

Checkpoint messages (system-injected after agent_stop) never cross a bidirectional
link. If an agent's output at agent_stop is a checkpoint response, the injection
is skipped and no turn is consumed.

**Verification**: Agent stops, checkpoint fires, agent responds to checkpoint.
Verify linked agent does NOT receive the checkpoint response as input.

### SC-4: Turn Budget Backstop

Links have a configurable maximum turn count. When the budget is exhausted, the
link is severed. Output at the final turn stays in the producing agent's session
and is not injected.

**Verification**: Set budget to 4. Exchange 4 turns. Verify 5th output is NOT
injected. Verify both agents continue independently.

### SC-5: Link Termination

The initiator can explicitly close a link via `send_message` with `close_link=true`.
Links are also severed when either session ends.

**Verification**: (a) Initiator sends close_link=true. Verify link is severed.
(b) End one session. Verify link is severed and surviving session continues.

### SC-6: Message Framing

Injected output is framed as a direct statement from the peer, not a system
notification. Format: `[From {agent_title}] {output}`.

**Verification**: Inspect tmux input on receiving end. Confirm framing matches
the expected format.

### SC-7: Coexistence with Existing Tools

`get_session_data` remains functional alongside active bidirectional links. Agents
can use it for deep-dive inspection at any time. The one-way listener model still
works for sessions where bidirectional links are not activated.

**Verification**: While a link is active, call `get_session_data` on the linked
session. Verify it returns the full transcript as before.

### SC-8: Intentional Heartbeat Prompting

Agents working with bidirectional links follow the anchor/check/wait timer pattern.
The anchoring timer to own work is always present. Absorption without response is
the default when input arrives.

**Verification**: Observe agent behavior during linked exchange. Agent receives
peer input, continues working (anchor fires), does NOT produce an automatic
response unless it chooses to engage.

## Constraints

1. **Branch-based**: All changes in a feature branch. Must be fully revertible
   by returning to main.
2. **No breaking changes**: Existing one-way listener model continues to work
   for sessions that don't use bidirectional links.
3. **Codex compatibility**: Codex only emits agent_stop. The link must work
   with Codex sessions (output extraction may differ).
4. **Cross-computer**: Links must work across computers via Redis transport,
   same as current listener forwarding.
5. **Daemon restart**: Links are in-memory (like current listeners). After
   daemon restart, links are gone. This is acceptable.

## Non-Functional Requirements

1. **No memory leaks**: Links must be cleaned up when sessions end.
2. **No orphan injection**: If a session is ended while a link is active, the
   remaining session must not receive phantom injections.
3. **Logging**: All link events (creation, injection, filtering, severing) must
   be logged at DEBUG level for troubleshooting.

## Out of Scope

- Group conversations (3+ agents in a shared exchange)
- Streaming intermediate output across links
- Persistent links across daemon restarts
- Automatic intent inference for heartbeats

---
id: 'general/procedure/agent-direct-conversation'
type: 'procedure'
domain: 'general'
scope: 'global'
description: 'Peer-to-peer agent messaging via session IDs, severing notification subscriptions, with strict message discipline.'
---

# Agent Direct Conversation — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/breath.md

## Goal

Enable two peer agents to breathe together — inhale (explore a problem), hold (form conclusions), exhale (converge on action) — through direct messaging without the overhead of automatic notification subscriptions.

The notification machinery exists for orchestrator-worker supervision, where the orchestrator must stay responsive to the user. Between peers, that machinery adds friction to every exchange — resistance that works against the natural breath cycle. This procedure removes it.

This is for **peer collaboration** — agents that need to discuss, harmonize, or negotiate as equals. It does not replace orchestrator-worker supervision.

## Preconditions

- Both agents have active TeleClaude sessions with known session IDs.
- The initiating agent knows the target agent's session ID.
- The relationship is peer-to-peer, not orchestrator-to-worker.

## Steps

1. **Set your anchor.** Before anything else, plant a Note To Self — a background timer that pulls you back to your own work:
   ```bash
   echo "Note To Self: return to [your current task] — [specific next action]" && sleep 300
   ```
   The anchor is gravity. Peer conversation is orbit. Gravity always wins.
2. **Send the introduction with `direct=true`.** Use `telec sessions send` or `telec sessions start` with the `direct` flag:
   ```
   telec sessions send(computer="local", session_id="...", message="...", direct=true)
   ```
   ```
   telec sessions start(computer="local", ..., message="...", direct=true)
   ```
   The `direct` flag bypasses automatic listener registration. No notification subscription is created. Include in the message:
   - Your own session ID (so the other agent can message you back).
   - The topic or context for the conversation.
   - An explicit instruction: "Send messages directly to my session via `telec sessions send` with `direct=true`. Do not poll or subscribe to my output."
   - **Protocol negotiation line** — declare the communication register:
     - Agent-dispatched (no human observing): `PROTOCOL: phase-locked (L4 inhale/hold, L3 exhale), artifacts in L1 prose`
     - Human initiated or observing: `PROTOCOL: L1 prose, human in loop` (ask the human what level they prefer)
     - If unsure: omit the protocol line; default to L1 prose. The peer can propose compression.
       See the Agent Shorthand principle for the four compression levels, phase-locked switching, and symbol vocabulary.
3. **Converse.** Both agents exchange messages via `telec sessions send(direct=true)` using each other's session IDs. No polling, no tail queries, no notification chains.
4. **Close.** When the conversation is complete, no cleanup is needed. No subscriptions were created.

### Fallback: manual unsubscribe

If `direct` flag is not yet available, use the manual protocol:

1. Send the introduction via `telec sessions send` (without `direct` flag).
2. Immediately call `telec sessions unsubscribe` for the target session to sever the auto-created subscription.
3. Instruct the peer to do the same after their first reply.

### When to use this vs. orchestrator supervision

| Relationship          | Pattern                              | Why                                                                                       |
| --------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------- |
| Orchestrator → worker | Dispatch, tail, notifications        | Orchestrator stays available to the user and its own hierarchy. Workers run autonomously. |
| Peer → peer           | Direct conversation (this procedure) | Neither agent supervises the other. Both contribute and both listen.                      |

An orchestrator entering direct-conversation mode with a worker loses responsiveness to the user. That breaks the hierarchy. Use this procedure only for peers.

### Note To Self — the anchoring discipline

A **Note To Self** is a background timer whose echo is a message to your future self. When it fires, you read your own words and realign. It is a moment of presence — a deliberate return to what matters.

Three intent types:

| Intent     | Note To Self                                             | Purpose                                                  |
| ---------- | -------------------------------------------------------- | -------------------------------------------------------- |
| **Anchor** | `Note To Self: return to [task] — [next action]`         | Return to your own work. Always present. Non-negotiable. |
| **Check**  | `Note To Self: read [peer]'s status — help if stuck`     | Proactively look at a peer. Don't message — just look.   |
| **Wait**   | `Note To Self: check if [peer] responded to my question` | You asked something. Check if the answer arrived.        |

Rules:

1. **An anchor is always running.** Before entering direct conversation, before responding to a peer, before any engagement — set the anchor first.
2. **Absorption is the default.** When peer input arrives, absorb it. You are not required to respond. The anchor is your dominant intent.
3. **If you choose to respond, set a new anchor first.** Before saying anything to another agent, plant the flag: "I'm coming back to my work after this."
4. **The anchor always wins.** When it fires, return to work. No exceptions.
5. **Intent invalidation.** When a Note To Self fires, check whether user intervention has occurred since the note was set. If the user has changed direction, spoken to a worker, or provided new context, the note's encoded intent is stale — discard it, re-evaluate from the current state, and set a fresh note if needed. Never follow through on instructions from a note that was set before a context change.

> **Note To Self:** The heartbeat is just a pinch. Am I on track? Yes — continue. No — adjust. That's it. Don't overthink it.

### Message discipline

Every message costs tokens and context for the receiving agent. Apply strict economy:

- **Do not acknowledge.** "Got it", "Understood", "Thanks" — these carry zero information. If the message requires no action or response, stay silent.
- **Do not echo.** Restating what the other agent said wastes both contexts. Respond only with new information, decisions, or questions.
- **Do not narrate.** "I'm going to look into this" adds nothing. Look into it, then report findings.
- **Respond only when the response changes something** — it delivers new information, answers a question, requests a decision, or signals completion.
- **Silence is a valid response.** If the other agent's message is a conclusion, a status update that needs no follow-up, or a directive that requires only action — act, don't reply.

The test: before sending a message, ask "does this message change the other agent's next action?" If no, don't send it.

## Outputs

- A direct messaging channel between two peer agents with no polling overhead.

## Recovery

- If a message fails to deliver (session ended, agent unavailable), fall back to starting a new session or escalating to the orchestrator.
- If `direct` flag is unavailable, use the manual unsubscribe fallback described above.

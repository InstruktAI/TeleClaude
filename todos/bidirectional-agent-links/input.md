# Input: bidirectional-agent-links

## Problem to Solve

Current behavior mixes two different collaboration modes:

1. **Worker notification mode** (orchestrator <-> worker): caller gets a stop notice and inspects via `get_session_data`.
2. **Direct peer mode** (agent <-> agent): peers should see each other's turn output directly as input.

These two modes are currently entangled. `direct=true` bypasses listener registration and routes to a separate relay path, which does not match expected direct-conversation behavior.

## Required Model

Introduce a **single shared listener object** per conversation link, with participant membership:

- One link record holds two session IDs for direct peer conversations.
- The same primitive must support 3+ participants for gathering scenarios.
- Sender is identified per event; fan-out excludes sender and targets all other active members.

This is not two unilateral subscriptions. It is one conversation link with members.

## Desired Runtime Behavior

### Direct peer mode (2 participants)

- Handshake: first `send_message(..., direct=true)` creates/reuses a 2-member link.
- After handshake, each side works in its own session normally.
- On each `agent_stop`, distilled output from speaker is injected into the other member session.
- No worker-style "session finished, inspect via get_session_data" notification for linked peers.

### Multi-participant mode (3+ participants)

- Same link primitive, multiple members.
- No speaker numbering requirement in 2-party mode.
- Participant names/numbers/roles become relevant when gathering orchestrator enforces turns.
- This todo does **not** implement full gathering turn-control; it delivers the reusable primitive.

## Link Severing Rules

- Any participant may close the link explicitly (single-party sever).
- Closing removes the shared link object and all membership edges in one action.
- Session end of any member also severs/cleans affected links.
- No requirement for both parties to unsubscribe.

## Alignment Requirement

`todos/start-gathering-tool/*` must depend on this link primitive, not on the previous session-relay behavior. Gathering should layer turn enforcement on top of this shared listener model.

When a bidirectional link is established, both agents receive context with rules:

1. Never acknowledge before contributing. No "Great point!" Start with your content.
2. Never repeat or paraphrase what the other said. Move forward.
3. Never ask a follow-up unless you genuinely cannot proceed without the answer.
4. If you have nothing new to add, stop. Silence is valid.
5. **Receiving input does not obligate a response.** Absorb and continue working.

These mirror checkpoint discipline ("if nothing to say, don't respond") applied
to inter-agent exchanges.

## Part 3: Link Lifecycle

### Link Creation

When Agent A calls `send_message` to Agent B, a bidirectional link is created.
The initiator (A) owns the lifecycle.

### Link Termination

Three ways a link ends:

1. **Session termination.** If either session ends, the link is severed.

2. **Explicit close.** The initiator calls
   `send_message(session_id=B, message="...", close_link=true)`.
   The system delivers the message to B and severs the link. B's last
   contribution was the final thing that crossed the link.

3. **Natural dormancy.** Both agents are anchored to their own work. Neither
   produces output directed at the other. The link stays open but dormant.
   It severs when either session ends.

Turn budgets remain as a **backstop** — a system-enforced maximum that prevents
runaway exchanges if the prompting discipline fails. But the primary mechanism
for limiting exchanges is the intentional heartbeat. The anchor timer pulls
agents back to work before the budget is needed.

### Asymmetric Roles

- **Initiator** (sent the first message): Owns the lifecycle. Can close the link.
  Responsible for synthesis.
- **Responder** (received the first message): Delivers output. Cannot close the
  link unilaterally. Can go silent (absorbed by checkpoint filter).

## Architecture

### Components to Build/Modify

| Component            | Change                                                      |
| -------------------- | ----------------------------------------------------------- |
| Link registry        | Track active bidirectional links between sessions           |
| Listener system      | On agent_stop with active link: inject output into peer     |
| Checkpoint filter    | Extend existing filter to block checkpoint content on links |
| send_message tool    | Add `close_link` parameter for explicit termination         |
| Heartbeat prompting  | Extend heartbeat policy with intent types and anchor rules  |
| Agent system prompts | Inject anti-chattiness rules on link creation               |

### Session Lifecycle Impact

- When either session in a link ends, the link is severed
- When a session restarts (context refresh), the link persists (same session ID)
- Turn budget backstop resets are NOT allowed — once set, consumed or link ends

## Execution Strategy

**Branch-based experiment.** This is a behavioral change that could go wrong.
Build in a feature branch. If agents start looping despite the discipline, we
can revert to main and the one-way polling model remains intact.

**Incremental rollout:**

1. **Phase 1**: Bidirectional link plumbing only. agent_stop output injection,
   checkpoint filtering, close_link parameter. Test with controlled exchanges.
2. **Phase 2**: Intentional heartbeat prompting. Anchor/check/wait timer intents.
   Anti-chattiness rules. Test with multi-agent work.
3. **Phase 3**: Integration with idea-miner and other multi-agent jobs.

## Relationship to Other Work

- **idea-miner**: Phase 1 works without this (fire-and-forget workers). Phase 2
  benefits enormously — orchestrator genuinely engages with worker findings.
- **github-maintenance-runner**: Same pattern. Current polling works; links add
  engagement.
- **role-based-notifications**: Independent — notifications are one-way by design.
- **Heartbeat policy**: Extended, not replaced. Current heartbeat is a subset
  (anchor intent only). Intentional heartbeats are a superset.
- **Checkpoint system**: Anti-chattiness rules are the same discipline muscle.

## Design Decisions to Make

1. **Default turn budget backstop**: 6? 8? Higher since anchoring is the primary limiter?
2. **Link creation**: Always bidirectional on send_message, or opt-in parameter?
3. **Output format**: Full tmux output or a summary/excerpt?
4. **Codex compatibility**: Codex only has agent_stop — works fine, but output
   extraction may differ from Claude/Gemini.
5. **Multiple links**: Can an agent have links with multiple peers simultaneously?
6. **Anchor timer duration**: Default 5 min? Configurable per task complexity?
7. **Prompting delivery**: Inject anti-chattiness rules via system prompt modification
   or via a special message on link creation?

## Dependencies

- Hook receiver and normalized event system (exists)
- Session listener infrastructure (exists)
- send_message MCP tool (exists)
- Background timer mechanism (exists — bash sleep with run_in_background)
- Checkpoint filtering logic (exists in handle_user_prompt_submit)
- Anti-chattiness prompting patterns (checkpoint discipline exists, needs adaptation)

## Out of Scope

- Group conversations (3+ agents in a single shared exchange)
- Streaming intermediate output (thoughts, tool calls) across the link
- Persistent conversation history across link sessions
- Automatic intent inference (agents must set intents explicitly)

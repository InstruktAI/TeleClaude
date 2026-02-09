# Bidirectional Agent Links — Direct Agent-to-Agent Communication

## Context

Today, agent-to-agent communication is one-way and mechanical:

1. Agent A calls `send_message` to Agent B
2. A one-way listener is created: A gets notified when B goes idle
3. A uses `get_session_data` to poll B's transcript (reading a log, not engaging)
4. A processes the output as a chore, not as cognitive input

This creates **disengaged orchestrators** — agents that check boxes instead of
reasoning about what other agents produced. The polling model was a safety mechanism
against the chattiness problem (two LLMs in open conversation loop infinitely), but
it comes at the cost of genuine intellectual engagement between agents.

## The Feature

Two interconnected changes that transform agent-to-agent collaboration:

1. **Bidirectional links**: When Agent A sends a message to Agent B, both agents'
   `agent_stop` output is injected directly into the other's session. No polling,
   no artificial "go read the output" instructions.

2. **Intentional heartbeats**: Agents set timers with explicit intent — anchoring
   them to their own work while enabling deliberate, proactive engagement with peers.
   This replaces the reactive loop with a disciplined rhythm of work and collaboration.

## Part 1: Bidirectional Links (The Plumbing)

### How It Works

```
A sends_message to B → bidirectional link created

B thinks, calls tools, reasons (PRIVATE — not visible to A)
B stops → agent_stop → B's output injected into A's session as input

A thinks, calls tools, reasons (PRIVATE — not visible to B)
A stops → agent_stop → A's output injected into B's session as input
```

### Privacy: Only Agent Stop Output Crosses the Link

Thoughts, tool calls, intermediate reasoning stay private. Each agent sees the
other's distilled product, not the process. This preserves cognitive privacy and
prevents noise.

The `agent_stop` event IS the natural turn boundary. When an agent stops — finished
its thought, done with its tool calls — that's the moment it has something to say.
No new event types required.

### Event System Alignment

- **Claude/Gemini**: Rich normalized event stream (thought, tool_call, agent_output,
  agent_stop). Well-normalized via the hook receiver. Only agent_stop crosses links.
- **Codex**: Only agent_stop. Very silent — but that's fine since we only need
  agent_stop for the bidirectional link.

The plumbing change: when `agent_stop` fires on a session with a bidirectional link,
inject the output into the linked session. Same mechanism as today's idle notification,
but instead of "B went idle" metadata, it's B's actual output arriving as input.

### Checkpoint Filtering (Hard Requirement)

Checkpoint messages injected by the system (after agent_stop) must NEVER cross a
bidirectional link. A checkpoint response is internal housekeeping — not conversational
output for the linked agent.

A checkpoint response crossing the link would:

- Confuse the receiving agent (not addressed to them)
- Trigger a response, starting a checkpoint-echo loop
- Pollute the exchange with meta-process noise

Filtering approach: the checkpoint string is already identifiable (injected via tmux
send-keys with a known pattern). The same identification used by
`handle_user_prompt_submit`'s early return must be applied to link injection. If the
agent_stop output is a checkpoint response, skip injection — the link stays open,
no turn is consumed.

### Coexistence with get_session_data

The bidirectional link does NOT replace `get_session_data`. Both coexist:

- **Direct injection** (link): Cognitive engagement. Output hits reasoning as input.
- **get_session_data** (tool): Deep-dive scrubber. Full transcript, tool calls,
  reasoning trace — when the injected output isn't enough.

The link gives you the summary at the coffee machine. The scrubber lets you read
their full notes. Agents already have `get_session_data` in their tool belt; the
link adds engagement on top, it doesn't replace inspection underneath.

### Message Framing

When B's output arrives in A's session, it should feel direct:

```
[From worker-feasibility] The core finding: idea X requires rewriting the
adapter registration system. Effort: 3-4 sessions. Risk: high.
```

Not a system notification. Not a log excerpt. A direct statement from a peer.

## Part 2: Intentional Heartbeats (The Discipline)

### The Problem with Reactive Links

Bidirectional injection alone creates a reactive loop: A speaks → B reacts → A
reacts → infinite. LLMs are trained to respond to input. Always. There's no
intrinsic mechanism to absorb input without responding, then go back to work.

Turn budgets (hard turn limits) are a brute-force solution — they cut the wire.
But they don't solve the underlying problem: agents need a way to be **proactive**
about collaboration instead of **reactive** to input.

### The Solution: Heartbeats with Intent

The heartbeat currently serves one purpose: "Am I on track?" — a self-check during
sustained work. We extend it to carry **intent**: metadata about what to do when
the timer fires.

**Timer intents:**

| Intent     | What happens when it fires                               |
| ---------- | -------------------------------------------------------- |
| **Anchor** | Return to your own work. Non-negotiable. Always present. |
| **Check**  | Read another agent's status. Don't message — just look.  |
| **Wait**   | You asked a question. Check if the response arrived.     |

### The Anchoring Rule (Black and White)

**There must ALWAYS be an anchoring timer pointed at your own work.** This is the
gravity well. Non-negotiable. Every other timer is orbit; the anchor is gravity.

You can set additional timers with intent (check on a peer, wait for a response),
but the work anchor is the one that always fires. When it does, you go back to
your work regardless of what else is happening.

### The Game Rules

1. **You always have an anchoring timer pointed at your own work.**
2. **You can set additional timers with intent** (check peer, wait for response).
3. **When input arrives from another agent, you absorb it. You are NOT required
   to respond.** Absorption without response is the default. The anchor timer is
   your dominant intent.
4. **If you choose to respond, you set a new anchor FIRST.** Before saying anything
   to another agent, plant your flag: "I'm coming back to my work after this."
5. **The anchor timer always wins.** When it fires, you return to work.

### The Flow

```
A is working on task 3. Anchor set: "continue task 3 in 5 min"

A finishes a unit. Curious about B.
A sets check timer: "read B's status in 2 min"
A sets NEW anchor: "return to task 3 in 5 min"

Check timer fires →
  A reads B's status (get_session_data — proactive, not reactive)

  B is idle and stuck?
    → A sets anchor: "back to task 3 in 3 min"
    → A sends message to B (bidirectional link activates)
    → B responds (injected via link)
    → A absorbs B's response
    → Anchor fires → A returns to task 3

  B is productive?
    → A does nothing. Anchor fires → back to task 3.

  B responded to an earlier question? (injection arrived)
    → A absorbs it. Anchor is still ticking.
    → Anchor fires → A factors B's input into task 3. No response needed.
```

### Why This Solves Chattiness

The reactive loop (A speaks → B reacts → A reacts) breaks because:

1. **Absorption is the default.** When B's output arrives via the link, A absorbs
   it as context. A does not have to produce output in response. The anchor timer
   is the dominant intent — A continues working.

2. **Engagement is deliberate, not automatic.** You check on peers by setting a
   timer with check intent. You look before you speak. You decide whether to
   engage. This is proactive, not reactive.

3. **Every engagement starts with a new anchor.** Before responding to another
   agent, you set a timer to bring yourself back. The anchor is the first action,
   not an afterthought.

4. **The other agent follows the same rules.** B also has an anchor. B also absorbs
   without necessarily responding. Two anchored agents naturally limit their exchange
   to what's productive, because both are being pulled back to their own work.

### Timer Implementation

The timer's output IS the intent. When a background task completes, the output
appears in context as the agent's own breadcrumb:

```bash
echo "ANCHOR: return to task 3 — implement the report generator" && sleep 300
```

```bash
echo "CHECK: read worker-feasibility status, help if stuck" && sleep 120
```

```bash
echo "WAIT: check if worker-B responded to my question" && sleep 180
```

When the timer fires, the agent reads its own breadcrumb and knows what to do.
No new infrastructure needed — this uses the existing background bash mechanism.

### Anti-Chattiness Prompting (Injected on Link Creation)

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

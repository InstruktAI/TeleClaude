---
id: 'general/procedure/peer-discussion'
type: 'procedure'
domain: 'general'
scope: 'global'
description: 'Two peer agents discuss a topic together — segmenting the work, dispatching subagents in parallel, converging findings, and reporting to the user.'
---

# Peer Discussion — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-direct-conversation.md
- @~/.teleclaude/docs/general/principle/agent-shorthand.md

## Goal

Enable two peer agents to cover a topic together — each owning a segment, working in parallel, converging via L4/L3, and delivering a single L1 report to the user. The human does not drive the discussion; agents do the work and present findings.

## Preconditions

- A topic or artifact set has been provided (todos, specs, docs, a question).
- The primary agent can start a peer session via `telec sessions start`.

## Steps

1. **Read the landscape.** Glance titles and structure of the artifact set. Do not deep-dive — that is subagent work.

2. **Segment by natural domain boundary.** Split the artifact set into two roughly equal halves. Primary takes one half; peer takes the other. Prefer splits where the two halves are independent — minimizing cross-segment assumptions.

3. **Create a shared scratchpad.** Write `/tmp/peer-discussion-{slug}.md` with the segment assignments. Both agents write findings there under `## Agent A` and `## Agent B` headers.

4. **Start the peer session** via `telec sessions start` with:
   - The peer's segment clearly described.
   - The scratchpad path.
   - Protocol negotiation line in the opening message: `⊢proto:phased L4↔L3 artifacts:prose` (same-model peer → L4 inhale/hold, L3 exhale).

5. **Work your segment in parallel.** Dispatch subagents for your half. Do not wait for the peer before starting.

6. **Write findings to scratchpad** under `## Agent A` when done.

7. **Signal peer via L4** when your segment is complete: `[hold] §AgentA done → scratchpad`. Then wait.

8. **Convergence.** When peer signals `[exhale]`, read the full scratchpad. Identify cross-segment patterns neither side would have named alone. Send L4 exhale confirmation.

9. **Write L1 report to user.** Consolidate both halves into a single structured report:
   - Build readiness or verdict table (if applicable).
   - Ranked findings by severity.
   - Cross-agent patterns (what both sides hit independently).
   - Immediate actions.

10. **End the peer session** via `telec sessions end`.

## Convergence timeout

If the peer does not signal `[exhale]` within a reasonable time, check the scratchpad. If findings are present, consolidate what exists and note the incomplete segment in the report. Do not block the user indefinitely.

## Outputs

- A shared scratchpad at `/tmp/peer-discussion-{slug}.md` with raw findings from both agents.
- A single L1 report delivered to the user.
- Optionally: a durable brief written to the project (e.g., `todos/{slug}/discovery-brief.md`) when findings should persist beyond the session.

## Recovery

- If the peer session fails to start, work the full artifact set alone using parallel subagents only.
- If a subagent returns incomplete results, note the gap explicitly in the report rather than omitting it.

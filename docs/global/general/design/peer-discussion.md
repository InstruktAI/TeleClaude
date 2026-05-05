---
id: 'general/design/peer-discussion'
type: 'design'
domain: 'general'
scope: 'global'
description: 'Reusable paired-analysis shape for two peer agents: segment, work in parallel, converge, and emit a single report.'
---

# Peer Discussion — Design

## Required reads

- @~/.teleclaude/docs/general/principle/breath.md
- @~/.teleclaude/docs/general/spec/agent-shorthand.md

## Purpose

Define the paired-analysis shape for two peer agents covering one topic
together. The design preserves collective mode throughout: segment the topic,
work in parallel within the pair, converge, and emit one report.

## Inputs/Outputs

| Component         | Receives                            | Produces                                  |
| ----------------- | ----------------------------------- | ----------------------------------------- |
| initiating agent  | topic or artifact set               | segment split, peer kickoff, final report |
| peer agent        | assigned segment, shared scratchpad | segment findings, convergence signals     |
| shared scratchpad | segment assignments and findings    | shared intermediate state for convergence |

Primary output:

- one final `L1` report to the user

Intermediate output:

- one shared scratchpad at `/tmp/peer-discussion-{slug}.md`

## Invariants

### Collective mode

Both agents remain in paired mode for the duration of the discussion. Segment
ownership does not convert the work into solo mode.

### Scratchpad convention

Peer discussion uses exactly one shared scratchpad:

`/tmp/peer-discussion-{slug}.md`

Both agents write findings there under stable agent-owned sections.

### Single-emitter rule

Exactly one agent emits the final user-facing report. The peer may contribute
findings and convergence signals, but does not independently report to the user
unless emitter authority has been explicitly reassigned.

### Protocol discipline

Peer discussion uses the agent-shorthand contract for protocol negotiation,
phase markers, and output validity. Invalid no-op output remains invalid inside
the pair.

## Primary flows

### Standard paired analysis

1. Read the topic or artifact set and split it along a natural boundary.
2. Create `/tmp/peer-discussion-{slug}.md` with segment assignments.
3. Establish the peer link with `telec sessions start ... --direct` or
   `telec sessions send <peer-session-id> "<intro>" --direct`, and state the
   segment plus protocol line.
4. Both agents work their assigned segments in parallel and write findings into
   the scratchpad.
5. When an agent finishes its segment, it signals the other side with a hold
   marker pointing to the scratchpad.
6. Both agents read the full scratchpad, converge in exhale, and extract the
   cross-segment picture.
7. The designated emitter writes the final `L1` report to the user.

### Signal sequence

Expected phase sequence:

- `[hold]` while each agent is still generating findings
- `[hold] §AgentX done -> scratchpad` when one side finishes its segment
- `[exhale]` once both sides are ready to converge
- final user report from the single emitter

## Failure modes

### Peer silence or stall

If the peer stops responding, inspect the scratchpad after a reasonable wait.
If usable findings exist, consolidate what is there and note the incomplete
segment in the report rather than blocking indefinitely.

### Peer unreachable

If the peer session cannot be established, the initiating agent covers the full
topic alone.

### Cross-agent contradiction

If convergence reveals real contradiction, name the tension explicitly. Do not
collapse it into a fake resolution just to finish the report.

### Missing scratchpad updates

If a peer signals progress without updating the scratchpad, request the missing
state once. If it still does not arrive, report the segment as incomplete.

## See Also

- ~/.teleclaude/docs/general/principle/communication-compression.md

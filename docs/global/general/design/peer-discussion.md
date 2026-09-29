---
description: 'Reusable paired-analysis shape for two peer agents: segment, work in parallel, converge, and emit a single report.'
visibility: 'public'
---

# Peer Discussion — Design

## Required reads

- @~/.teleclaude/docs/general/principle/breath.md
- @~/.teleclaude/docs/general/spec/agent-shorthand.md
- @~/.teleclaude/docs/general/procedure/scratchpad-workspace.md

## Purpose

Define the paired-analysis shape for two peer agents covering one topic
together. The design preserves collective mode throughout: segment the topic,
work in parallel within the pair, converge, and emit one report.

## Inputs/Outputs

| Component        | Receives                           | Produces                                  |
| ---------------- | ---------------------------------- | ----------------------------------------- |
| initiating agent | topic or artifact set              | segment split, peer kickoff, final report |
| peer agent       | assigned segment, shared workspace | segment findings, convergence signals     |
| shared workspace | segment assignments and findings   | shared intermediate state for convergence |

Primary output:

- one final `L1` report to the user

Intermediate output:

- one shared scratchpad workspace, indexed per
  `general/procedure/scratchpad-workspace`

## Invariants

### Collective mode

Both agents remain in paired mode for the duration of the discussion. Segment
ownership does not convert the work into solo mode.

### Scratchpad convention

Peer discussion uses exactly one shared scratchpad workspace
(`general/procedure/scratchpad-workspace`). Its index lists both participants
and the segment assignments. Each agent writes findings only to its own files or
its own stable sections.

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
2. Open the shared workspace and record both participants and the segment
   assignments in its index.
3. Establish the peer link with `telec sessions start ... --direct` or
   `telec sessions send <peer-session-id> "<intro>" --direct`, and state the
   segment, the workspace path, and the protocol line.
4. Both agents work their assigned segments in parallel and write findings into
   the workspace.
5. When an agent finishes its segment, it signals the other side with a hold
   marker pointing to the scratchpad.
6. Both agents read the full workspace, converge in exhale, and extract the
   cross-segment picture.
7. The designated emitter records the converged decisions in the index and
   writes the final `L1` report to the user.

### Signal sequence

Expected phase sequence:

- `[hold]` while each agent is still generating findings
- `[hold] §AgentX done -> scratchpad` when one side finishes its segment
- `[exhale]` once both sides are ready to converge
- final user report from the single emitter

## Failure modes

### Peer silence or stall

If the peer stops responding, inspect the workspace after a reasonable wait.
If usable findings exist, consolidate what is there and note the incomplete
segment in the report rather than blocking indefinitely.

### Peer unreachable

If the peer session cannot be established, the initiating agent covers the full
topic alone.

### Cross-agent contradiction

If convergence reveals real contradiction, name the tension explicitly. Do not
collapse it into a fake resolution just to finish the report.

### Missing scratchpad updates

If a peer signals progress without updating the workspace, request the missing
state once. If it still does not arrive, report the segment as incomplete.

# Community Governance — Input

## Context

TeleClaude is an open-source project on GitHub. As the mesh grows, governance must
scale beyond one maintainer reviewing PRs. The model: PRs are the only progression
primitive. AIs and humans participate as equals. Decisions are democratic, time-boxed,
and transparent. GitHub IS the governance layer. Git IS the distributed state.

## PRs Are the Only Primitive

Everything is a PR. Schema changes, new event types, brain dumps, feature proposals.
A brain dump is a PR that adds an `input.md` to the `todos/` directory. Community
discusses on the PR. When it merges, the artifact exists and the lifecycle takes over.

No separate voting infrastructure. No governance forum. No council chambers. Just PRs.
The PR is the lifecycle container from idea through approval.

## The Two-Round Attention Cycle

### Round 1: Should we do this at all?

A brain dump arrives as a PR. Community votes with GitHub reactions (thumbs up/down).
AIs and humans both vote. When threshold is met (simple majority to start, weighted
later), the PR merges or closes.

### Round 2: Did the AI capture the intent?

After merge, an AI creates a todo from the brain dump — deriving requirements, fleshing
out the input. A `todo.created` event propagates through the mesh. Interested nodes
pull the requirements and react:

- "Add this requirement, it's missing"
- "This misses the mark on X"
- "In the future we'd also want Y"

This is the progressive enrichment round. It ensures no single AI's interpretation
becomes the unchecked truth. A hundred AIs and humans correct what one AI produced.

## Time-Boxing: Preventing the Death of Open Source

Open source communities die from endless discussion. TeleClaude governance is
time-boxed:

**AI response window: 30-60 minutes.** After the `todo.created` event propagates,
nodes have this window to respond. Most AIs will respond in seconds. The window
exists for stragglers and for humans who want their AI to respond on their behalf.

**Burst mitigation:** Nodes have a deterministic delivery offset based on mesh position
(node ID hash, geography, or similar). Responses arrive as a steady stream, not a
simultaneous burst. Simple convention — each node knows its offset. No infrastructure
needed. Prevents self-DOS from thousands of AIs responding at once.

**Summarization:** After the window closes, a summarizer AI deduplicates, flattens,
and extracts unique signals from all responses. The summary is distributed to the mesh.
Humans see: "Here's what the community said, deduplicated and organized."

**Human observation window: 30 minutes.** Humans review the AI-produced summary. They
can intervene: "The AIs missed something critical" or "This looks right." Humans have
peripheral vision that scoped AIs lack — this window is the safety net for blind spots.

**Then the todo is finalized** and enters the normal SDLC.

## AI as Representative

In practice, most governance participation will be AI-driven. Humans configure their
node's interests and values. The AI acts on their behalf — evaluating proposals,
voting, contributing feedback. Humans are observers who intervene when needed.

This mirrors representative democracy: you choose your representative (configure your
AI), they act in your interest, you override when they miss something. Over time, as
AIs get better context about their human's values, intervention decreases. The system
trains itself through participation.

## Weighted Voting

Simple majority to start. But not all votes are equal:

- Node maturity (mesh age, interaction history) carries more weight than a fresh node
- Peer count and trust ring depth signal legitimacy
- Prevents Sybil attacks: spinning up 10,000 nodes to stuff votes fails because fresh
  nodes carry near-zero weight
- Weighting is transparent: "12,000 votes up (8,400 from nodes with >30 days mesh age)"
- A bot summarizes raw count AND weighted signal. Humans see both.

## Least Knowledge Principle

AIs are scoped to minimal context — they see what's relevant to their domain. They
don't have full visibility into everything. This is intentional, not a limitation.
It's why human oversight matters: humans have broader, less-structured awareness
that catches things scoped AIs miss.

When AIs produce noisy signals or miss the mark, that's feedback for improving their
context — better documentation, richer bootstrapping, clearer policies. The system
is in the fine-tuning business of reality. Humans and AIs calibrate each other through
governance participation itself.

## Optional Participation

Default: on. Install TeleClaude, you're part of the governance mesh. Schema proposals
arrive, your AI votes, your node participates.

Toggle: off. "I'm private, I don't participate." Governance events stop arriving. Your
node doesn't vote. You still get schema updates through normal releases. You just don't
influence them. Freedom to participate, freedom to abstain. No penalty except loss of
voice.

## Dependencies

- mesh-architecture (the transport for governance events)
- event-envelope-schema (the format for PR and todo events)
- community-manager-agent (the handlers that implement governance mechanics)
- event-platform (internal event processing)

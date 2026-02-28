# Community Manager Agent — Input

## Context

The community governance model needs operational handlers — not a monolithic bot, but
a set of focused event consumers that implement governance mechanics on GitHub. Each
handler is a small, single-purpose thing. Same pattern as internal notification service
consumers.

## Handler: Voting Threshold Detection

Monitors PR reactions. When the voting threshold is met (configurable — simple majority
to start, weighted later), triggers the next lifecycle step:

- Approved? Signal for merge or todo creation.
- Rejected? Signal for close with summary of objections.

Inputs: GitHub PR reactions (via webhook or polling).
Outputs: Lifecycle transition event.

## Handler: Todo Creation from Brain Dumps

When an approved brain dump PR merges, this handler:

1. Reads the merged `input.md`
2. Derives initial requirements (AI-powered)
3. Writes the todo artifacts
4. Emits `todo.created` event to the mesh
5. Updates the PR with a link to the created todo

The todo creation is what triggers Round 2 of the attention cycle — community
review of the AI-produced requirements.

## Handler: Feedback Summarization

After the response window closes (30-60 minutes post `todo.created`):

1. Collects all responses from the mesh
2. Deduplicates — multiple nodes saying the same thing = one signal
3. Flattens — extracts unique requirements, concerns, suggestions
4. Produces a structured summary
5. Distributes summary to the mesh for human observation window
6. Updates the todo with the consolidated feedback

This is the most AI-intensive handler. It needs to distinguish genuine new signals
from noise, echo, and repetition.

## Handler: Schema Proposal Distributor

When a `schema.proposed` event is created (someone opened a PR changing the schema):

1. Wraps the proposal in a mesh event
2. Distributes to all governance-participating nodes
3. Collects reactions within the time window
4. Summarizes votes (raw count + weighted by node maturity)
5. Posts summary to the GitHub PR

## Handler: Discussion Summarizer

For long-running GitHub discussions and PR threads:

1. Periodically summarizes discussion state
2. Extracts action items, open questions, consensus points
3. Posts summary as a comment for human consumption
4. Flags discussions that have stalled or need decision

## Architecture

These handlers are NOT a single service. They are independent event consumers that
subscribe to relevant events through the notification service. Each can be deployed,
updated, and scaled independently. They follow the same pattern as internal TeleClaude
notification consumers — the community manager is just a set of consumers pointed at
GitHub events instead of local events.

The GitHub API is the interface. Reactions, comments, PR status — all via API.
No custom GitHub App needed initially — a bot account with appropriate permissions
is sufficient.

## Dependencies

- community-governance (the model these handlers implement)
- event-platform (event routing)
- mesh-architecture (event distribution)
- event-envelope-schema (event format)

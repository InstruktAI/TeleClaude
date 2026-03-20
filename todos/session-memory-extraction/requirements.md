# Requirements: session-memory-extraction

## Goal

Turn the existing session memory extraction job from bookkeeping-only into a
working pipeline that reads cleaned conversation deltas from long-lived sessions
and produces durable personal memories, business memories, and actionable items
through the existing TeleClaude infrastructure.

## Scope

### In scope

- Reading only the newly available cleaned conversation content for an eligible
  session.
- Extracting cross-project personal memories from that delta and persisting them
  with identity scope.
- Extracting project-scoped business memories from that delta and persisting
  them without identity scope.
- Extracting actionable follow-ups from that delta and publishing them through
  the channels subsystem.
- Removing the post-extraction `/compact` injection because no handler exists.

### Out of scope

- Changing which sessions are eligible for extraction.
- Changing how identity scope is resolved.
- Changing when bookkeeping timestamps are advanced.
- Changing mirror generation or mirror storage interfaces.
- Changing memory storage interfaces.
- Changing channels subsystem interfaces.
- Changing the shared structured-output summarizer helper.
- Changing idle-detection behavior in the maintenance service.

## Functional Requirements

### FR1: Transcript Delta Reading

The job must read only the cleaned conversation content that became available
after the last successful extraction boundary for a session.

- When no prior extraction boundary exists, the full cleaned conversation is
  eligible for extraction.
- When a prior extraction boundary exists, only content newer than that boundary
  is eligible.
- The returned text must be clean, human-readable conversation — not raw
  transcript records, tool-call noise, or compaction markers.
- When no new conversation content exists, the delta reader returns no work.
  [inferred]
- The data source must be the mirror system's already-cleaned output, not raw
  transcript files.
- [inferred] Because persisted mirrors expose cleaned session conversation text
  rather than per-message timestamp rows, the implementation must derive its
  incremental window from the mirror artifact and existing session bookkeeping.

### FR2: Personal Memory Extraction

The job must use the existing structured-output summarizer pattern to extract
durable personal facts from each transcript delta and persist them as
identity-scoped observations.

- Focus on user-level facts that remain useful across projects: preferences,
  communication style, domain knowledge, recurring needs, and similar durable
  context.
- Do not store session-specific operational chatter or transient state as
  personal memory.
- Each stored personal memory must be persisted with identity scope.
- The model output must map cleanly onto the existing observation persistence
  fields needed to save a memory entry.
- When no identity scope can be resolved, personal-memory extraction is skipped
  and the reason is logged. [inferred]
- When the model finds nothing worth storing, the step completes successfully
  without writing memories.

### FR3: Business Memory Extraction

The job must use the same structured-output summarizer pattern to extract
project-scoped business facts from each transcript delta and persist them as
unscoped observations.

- Extraction focus: product feedback, pain points, feature requests, domain
  context, and other facts relevant to the project as a whole.
- Stored business memories must not carry identity scope.
- Project scope is derived from the session's project context. [inferred]
- When the model finds nothing worth storing, the step completes successfully
  without writing memories.

### FR4: Actionable Items Extraction and Publishing

The job must use the same structured-output summarizer pattern to identify
actionable follow-ups in each transcript delta and publish them through the
channels subsystem.

- Actionable item types: bugs, feature requests, follow-ups, escalation triggers.
- Published items must preserve the extracted item category and a summary for
  downstream routing or review. [inferred]
- When no actionable items are found, the step completes successfully without
  publishing.
- [inferred] When the channels transport is unavailable, the job logs and skips
  publication instead of crashing the rest of the extraction pipeline.

### FR5: Remove Post-Extraction Compact Injection

The session-memory extraction flow must no longer inject `/compact` into tmux
after successful extraction.

- Remove the post-extraction command injection entirely.
- No replacement command is introduced as part of this todo.

## Acceptance Criteria

- [ ] Eligible sessions with new mirror content produce a cleaned conversation
      delta that excludes raw transcript records, tool noise, and compaction
      markers.
- [ ] Eligible sessions with no new mirror content produce no extraction work.
- [ ] Personal memories are stored with identity scope when durable personal
      facts are extracted.
- [ ] Personal-memory extraction is skipped when identity scope cannot be
      resolved. [inferred]
- [ ] Business memories are stored without identity scope when durable
      project-level facts are extracted.
- [ ] Actionable items extracted from a delta are published through the channels
      subsystem.
- [ ] All three extraction paths treat "nothing worth extracting" as a
      successful no-op.
- [ ] The existing dual-provider structured-output summarizer path is reused.
- [ ] The post-extraction `/compact` injection path is removed.
- [ ] [inferred] If the channels transport is unavailable, actionable-item
      publication is skipped with logging and does not abort the rest of the job.
- [ ] [inferred] A failure while processing one eligible session does not
      prevent later eligible sessions from being processed in the same job run.
- [ ] [inferred] Session bookkeeping advances only after a session's extraction
      work completes successfully.

## Constraints

- Reuse the existing shared structured-output summarizer pattern; do not
  introduce a second LLM client path.
- Reuse the existing memory persistence boundary for all saved memories.
- Reuse the existing channels publishing boundary for actionable items.
- Structured output schemas must be used for the extraction prompts.
- [inferred] The job remains idempotent at the session-window level: re-running
  the same successful extraction window does not create duplicate memories or
  duplicate actionable publications.

## Dependency / Prerequisites

- Mirrors are already being generated for eligible sessions.
- The memory database tables already exist.
- At least one supported summarizer provider is configured.
- [inferred] The channels transport may be unavailable in some deployments; that
  state must not crash the job.
- Existing session eligibility and bookkeeping behavior are treated as
  integration points, not redesigned here.

## Risks

- **LLM output quality**: Extraction quality depends on prompt design. Poor
  prompts may produce low-signal or noisy memories. Mitigated by using structured
  output schemas that constrain the response shape.
- **Token cost**: Running LLM extraction on every eligible session delta incurs
  API cost. Mitigated by the existing idle-threshold gating and the lower-cost
  models in the current summarizer path.
- **Mirror data availability**: If a session has no mirror (e.g., very short
  sessions, sessions that errored before mirror generation), delta reading will
  return None and extraction will be skipped — acceptable behavior.

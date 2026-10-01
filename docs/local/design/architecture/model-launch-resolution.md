---
description: One launch-model decision boundary at every computed agent-process launch, resolving per-mode ordered model chains against model-scoped availability.
---

# Model Launch Resolution — Design

## Required reads

@docs/local/spec/feature/agent_runtime/model-quota-recovery.md

## Purpose

Give every computed launch of an agent process — fresh dispatch, restart, and
revival — one decision boundary that turns the effective thinking mode into the
concrete launch model. Agent selection (the agent-dispatch boundary) decides _who_
runs; this boundary decides _which model_ that agent launches with, honoring the
agent's declared fallback chain and the currently recorded model-scoped
availability. It exists so model-specific quota exhaustion degrades one launch
decision instead of an agent, and so no launch site carries its own mapping logic.

## Inputs/Outputs

Inputs:

- Agent and effective thinking mode (mode resolution upstream is owned by the
  agent-dispatch boundary; this boundary never re-derives a mode).
- The agent's protocol declaration: a per-agent launch-flag template (how a model
  identifier and an optional effort render into CLI flags) and, per mode, the
  declared effort and the ordered default model list.
- The operator configuration override: an optional per-agent, per-mode ordered
  model list (`agents.<agent>.model_chains.<mode>`), whose schema and startup
  validation are owned by the config context. A configured chain replaces the
  default model list for that mode; omitted modes keep defaults.
- The active model-scoped availability records for the agent.
- The launch's ownership: the job role the launch carries, taken from the launch
  request at fresh dispatch and from the session record at restart and revival. A
  launch with no job role is human-owned.

Outputs:

- The selected model and its rendered launch flags, consumed by command assembly.
  Command assembly never reads mode mappings or availability itself.
- One structured warning when a non-first chain entry is selected, naming agent,
  mode, skipped model(s), selected model, launch ownership, and reason.
- A typed pre-session failure when no chain entry is eligible for the launch's
  ownership.

### Availability projection

The agent-runtime availability surface carries model scope explicitly so a model
record can never be read as agent-wide unavailability, and both scopes speak one
status vocabulary:

- **Write.** The agent-status request gains an optional model identity. A request
  without a model addresses the agent-wide row exactly as today; a request with a
  model writes or clears that (agent, model) record, accepts the same
  `available` / `degraded` / `unavailable` statuses the agent-wide row accepts,
  and never touches the agent-wide row.
- **Read.** The availability response stays keyed by agent. Each agent entry
  carries its agent-wide status, its until instant, and its reason, and gains a
  collection of active model records carrying the same three fields plus the
  model identity. An expired or absent record reports `available` and no model
  record appears for it.
- **Events.** The availability-change event gains an optional model-record
  payload: the model identity together with that record's status, until instant,
  and reason, or its clearance. A model-scoped change sets that payload and
  carries the _unchanged_ agent-wide fields, so a consumer that predates model
  identity observes no agent-wide change, while a model-aware consumer renders the
  record live from the event alone, with no refresh round-trip. An event without
  the model payload keeps today's agent-wide meaning exactly.
- **Consumers.** Agent-candidate eligibility continues to read agent-wide state
  only. The CLI availability listing renders model records beneath their agent
  entry and the TUI carries them in its availability projection; the
  launch-model resolver reads model records directly from the store, not from
  the projection. Every consumer reads the status field; none re-derives a state
  from a reason string or from a boolean.

## Invariants

- **Resolution at every computed launch, results recorded nowhere.** Session
  records pin agent, native transcript, mode, and the job role the launch carried
  — never a model, never rendered flags. When a model's status expires, the next
  computed launch returns to the primary with no cleanup.
- **One availability aggregate, two granularities.** The availability record's
  identity is (agent, model), with the empty model value designating the
  agent-wide operator row. Agent-wide rows keep today's semantics and remain the
  sole input to agent-candidate eligibility; model rows are consumed only by
  this boundary. Both share one expiry sweep and one availability-event path.
- **One typed status owns both granularities.** A record's state is exactly one of
  `available`, `degraded`, or `unavailable`, held as data with its own optional
  until instant and reason. No consumer infers a state from a reason string, from
  a boolean, or from the presence of an until instant, and no surface represents a
  model as unavailability-only. Expired statuses normalize to available under the
  one availability contract.
- **Ownership, not status, decides model eligibility.** A degraded subject is
  excluded from a launch that carries a job role and retained for a launch that
  carries none; an unavailable subject is excluded from both. The rule is one
  predicate over (status, ownership), applied to an agent candidate and to a model
  entry alike, so the two granularities can never drift apart.
- **Writes stay with intelligence.** Model rows are written through the
  agents-status surface by a parent that classified provider evidence; the
  resolver only reads. No code path classifies provider prose.
- **Chain contents are declared policy.** Defaults live in the protocol
  declaration; the config override selects and orders model identifiers from the
  agent's declared model-identifier set, validated at startup by the config
  context. The resolver never invents a model and never substitutes an agent.
- **Session-status truth is the stored agent status.** The stalled state and
  its reason are members of the agent status the agent_runtime context
  persists on each transition
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`). This design reads
  that status and never recomputes it from timestamps.

## Primary flows

- **Fresh dispatch.** Agent selection yields the agent; mode resolution yields
  the mode; the launch request yields the ownership; this boundary walks the
  mode's chain, skips entries the ownership excludes, renders the first eligible
  entry, and hands flags to command assembly. Non-first selection emits the
  structured warning.
- **Restart / revival.** The recorded agent, mode, and job role enter the same
  walk; the transcript is untouched. A session whose primary model its ownership
  excludes relaunches on the fallback and continues in place, and a human-owned
  session keeps a degraded primary across both operations.
- **Startup quota recovery.** The parent classifies captured terminal evidence,
  records the exhausted model through the agents-status surface, ends the stale
  session, and repeats the identical dispatch once; this boundary makes the retry
  land on the fallback.
- **Mid-session (stalled) quota recovery.** The stalled derivation surfaces the
  silent worker; the parent captures the pane, classifies, records the model, and
  restarts the session once; this boundary resolves the fallback at the restart's
  computed launch.

## Failure modes

- **Chain exhausted.** No model in the mode's chain is eligible for the launch's
  ownership: the launch fails with a typed error before any session or session row
  exists. Agent-wide status is untouched; the failure is the caller's normal
  unsuccessful outcome.
- **Invalid chain declaration.** A configured chain naming an unknown mode or a
  model identifier outside the agent's declared set fails config validation at
  startup, referencing the concrete config path — never surfacing at dispatch.
- **Availability read failure.** A storage read failure is not a missing record:
  resolution returns a distinct availability-state failure rather than silently
  treating the model as usable, mirroring the agent-dispatch eligibility rule.

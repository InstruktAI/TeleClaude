---
description: One launch-model decision boundary at every computed agent-process launch, resolving per-mode ordered model chains against model-scoped availability.
delivered_by:
  - model-quota-slow-fallback
---

# Model Launch Resolution — Design

## Required reads

@docs/project/spec/feature/agent_runtime/model-quota-recovery.md

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

Outputs:

- The selected model and its rendered launch flags, consumed by command assembly.
  Command assembly never reads mode mappings or availability itself.
- One structured warning when a non-first chain entry is selected, naming agent,
  mode, skipped model(s), selected model, and reason.
- A typed pre-session failure when every chain entry is unavailable.

### Availability projection

The agent-runtime availability surface carries model scope explicitly so a model
record can never be read as agent-wide unavailability:

- **Write.** The agent-status request gains an optional model identity. A request
  without a model addresses the agent-wide row exactly as today; a request with a
  model writes or clears that (agent, model) record, accepts `unavailable` with
  its until instant only, and never touches the agent-wide row.
- **Read.** The availability response stays keyed by agent. Each agent entry
  keeps its agent-wide fields unchanged — `available` and `status` derive from
  the agent-wide row alone — and gains a collection of active model records, each
  carrying its model identity, until instant, and reason. An expired or absent
  model record simply does not appear.
- **Events.** The availability-change event gains an optional model identity. A
  model-scoped change sets that identity and carries the _unchanged_ agent-wide
  fields, so a consumer that predates model identity observes no agent-wide
  change; only model-aware consumers render the model record. An event without
  model identity keeps today's agent-wide meaning exactly.
- **Consumers.** Dispatch candidate eligibility continues to read agent-wide
  state only. Operator surfaces (CLI availability listing, TUI) render model
  records beneath their agent entry; the launch-model resolver reads model
  records directly from the store, not from the projection.

## Invariants

- **Resolution at every computed launch, results recorded nowhere.** Session
  records pin agent, native transcript, and mode — never a model, never rendered
  flags. When a model's availability record expires, the next computed launch
  returns to the primary with no cleanup.
- **One availability aggregate, two granularities.** The availability record's
  identity is (agent, model), with the empty model value designating the
  agent-wide operator row. Agent-wide rows keep today's semantics and remain the
  sole input to dispatch candidate eligibility; model rows are consumed only by
  this boundary. Both share one expiry sweep and one availability-event path.
- **Model rows carry unavailable-until only.** Degraded is an agent-wide operator
  concept; a model is either usable or recorded unavailable with an explicit
  window. Expired rows normalize under the existing availability contract.
- **Writes stay with intelligence.** Model rows are written through the
  agents-status surface by a parent that classified provider evidence; the
  resolver only reads. No code path classifies provider prose.
- **Chain contents are declared policy.** Defaults live in the protocol
  declaration; the config override selects and orders model identifiers from the
  agent's declared model-identifier set, validated at startup by the config
  context. The resolver never invents a model and never substitutes an agent.
- **Session-status truth is a read-time derivation.** The stalled state (in a
  turn, observed activity still beyond the platform's stall threshold) is
  computed where agent status is already derived, from existing timestamps plus
  the current time; nothing is persisted, and any new activity self-heals the
  derivation back to active. The threshold is one internal configuration
  constant.

## Primary flows

- **Fresh dispatch.** Agent selection yields the agent; mode resolution yields
  the mode; this boundary walks the mode's chain, skips models with active
  records, renders the first available entry, and hands flags to command
  assembly. Non-first selection emits the structured warning.
- **Restart / revival.** The recorded agent and mode enter the same walk; the
  transcript is untouched. A session whose primary model is recorded unavailable
  relaunches on the fallback and continues in place.
- **Startup quota recovery.** The parent classifies captured terminal evidence,
  records the exhausted model through the agents-status surface, ends the stale
  session, and repeats the identical dispatch once; this boundary makes the retry
  land on the fallback.
- **Mid-session (stalled) quota recovery.** The stalled derivation surfaces the
  silent worker; the parent captures the pane, classifies, records the model, and
  restarts the session once; this boundary resolves the fallback at the restart's
  computed launch.

## Failure modes

- **Chain exhausted.** Every model in the mode's chain has an active record: the
  launch fails with a typed error before any session or session row exists.
  Agent-wide status is untouched; the failure is the caller's normal unsuccessful
  outcome.
- **Invalid chain declaration.** A configured chain naming an unknown mode or a
  model identifier outside the agent's declared set fails config validation at
  startup, referencing the concrete config path — never surfacing at dispatch.
- **Availability read failure.** A storage read failure is not a missing record:
  resolution returns a distinct availability-state failure rather than silently
  treating the model as usable, mirroring the agent-dispatch eligibility rule.

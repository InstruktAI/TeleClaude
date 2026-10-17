---
description: Bounded recovery when a selected model exhausts its own quota, persisted
  as model-scoped availability and resolved through per-mode ordered model chains.
---

# Model Quota Recovery — Spec

## What it is

Model-quota recovery preserves an orchestrated job when the selected model exhausts
its own allowance during startup while the provider and harness may still be usable.
The parent reads the failed runtime terminal, classifies the provider prose, records
the exhausted model as model-scoped availability, removes the stale session, and
retries the identical dispatch once. Thinking-mode resolution selects the launch
mapping through the agent's ordered model chain, so the retry — and every subsequent
dispatch while the record is active — runs the best available model without any
special mode token.

This recovery is distinct from provider availability. Exhaustion scoped to one model
does not make every model behind the provider unavailable and does not change the
agent-wide operator status.

Provider-wide quota or instability follows the provider-availability recovery
contract; it is not recorded as a model-scoped status.

## Canonical fields

### Model-scoped availability

The availability record carries an optional model identifier. A record without a
model is the agent-wide operator status; agent-candidate eligibility consumes only
those records, unchanged. A record with a model is consumed only by mode-to-model
resolution. Both granularities carry one status — `available`, `degraded`, or
`unavailable` — with an optional explicit until instant taken from the provider's
stated recovery window and a reason, and an expired status normalizes back to
available under the one availability contract. Intelligence, never keyword matching,
decides when a model record is written.

Status alone does not decide whether a model may launch; launch ownership completes
it. A launch that carries no job role is human-owned: a degraded model stays
selectable, so the configured primary remains that launch's default choice. A launch
that carries a job role is automatic work: a degraded model is skipped for the next
configured entry. Both ownerships skip an `unavailable` model. Ownership is read
from the launch's own job role at fresh dispatch and from the session record's job
role at restart and revival, so it survives both without pinning a model.

### Ordered model chains

Each agent's thinking-mode mapping is an ordered chain of entries. Every entry
carries its model identifier as data alongside its launch flags. Resolution selects
the first entry whose model is eligible under the launch's ownership; later
entries are fallbacks for the same declared intent. A single-entry chain is the
default and behaves exactly like today's one mapping.

Claude's `slow` chain is Claude Fable then Claude Opus, both at high effort. Codex
and Gemini currently declare single-entry chains, so no fallback exists for them.
Chain contents are declared per-agent policy: the platform ships defaults, and the
operator configuration may override them per agent and mode. The declaration
surface, its schema, and startup validation are owned by the configuration
contract (`local/projects/teleclaude/spec/teleclaude-config`); chain resolution consumes the
validated policy and never invents a model or substitutes another agent.

Chain resolution applies at every computed launch of an agent process — fresh
dispatch, restart, and revival alike. A session record pins the agent, the native
transcript, the thinking mode, and the job role its launch carried, never a model:
launch commands are always computed from the current mapping and the recorded
ownership, so continuation on a fallback model is the same computation the platform
has always performed when mappings change. No per-session launch state is recorded
anywhere; when a model's status expires, the next computed launch returns to the
primary automatically.

When resolution selects a non-first entry, it emits one structured warning naming
the agent, mode, skipped model, selected model, launch ownership, and reason. When no
entry in the chain is eligible for the launch's ownership, dispatch fails with a typed
error before session creation and the agent-wide status stays untouched.

### Evidence and retry boundary

Startup evidence comes from the supervised terminal when no native transcript exists.
The terminal is captured before the stale session is ended. Intelligence decides
whether the provider prose establishes model-specific exhaustion, and the model it
records is the one the failed dispatch resolved to — never a name extracted from
prose.

Mid-session evidence arises when a worker's turn dies without an agent stop and the
session derives `stalled`: the parent captures the still-live pane and applies the
same intelligence classification. Recovery for a stalled worker preserves its
transcript — the parent records the exhausted model and restarts the same session
once; the restart's computed launch resolves the fallback model and the work
continues in place.

The startup retry repeats the literal identical dispatch: job, project, arguments,
context, selected agent, and mode are all unchanged; only chain resolution may
select a different model. Both recovery forms end after one attempt. No fallback
mode token exists on any surface, public or internal.

### Use cases

#### UC-MQR-1: Terminal evidence supports transcriptless startup failure

#### UC-MQR-2: An operator's job continues after its model quota is exhausted

```gherkin
Given an operator has a scheduled job whose selected model exhausts its quota during startup
When the parent recovers the job
Then the job continues once on the next eligible model
And its recovery does not change the agent-wide operator status
```

#### UC-MQR-3: Recovery preserves the original dispatch

#### UC-MQR-4: Recovery never loops

#### UC-MQR-5: Provider-wide failure keeps provider availability semantics

#### UC-MQR-6: An active model record steers every subsequent dispatch

#### UC-MQR-7: An operator's primary model is used again after recovery

```gherkin
Given the operator's primary model has passed its stated recovery window
When a later job uses the configured model chain
Then it launches on the primary model again
And no stale fallback choice remains
```

#### UC-MQR-8: An exhausted chain fails dispatch without touching agent availability

#### UC-MQR-9: An operator can choose the model chain for an agent mode

```gherkin
Given an operator wants a different model preference for an agent's thinking mode
When they declare an ordered chain in the operator configuration
Then future launches follow that configured chain
And an invalid chain is rejected during configuration validation
```

#### UC-MQR-10: An operator's stalled worker continues in place after quota exhaustion

```gherkin
Given an operator's dispatched worker derives `stalled` during a turn
And the parent captures the pane and intelligence establishes model-specific exhaustion
When the parent recovers the worker
Then it records the exhausted model unavailable until the provider's stated window
And restarts the same session once, whose computed launch resolves the next available chain model
And the session's transcript and job context are preserved
And a failed restart triggers no further model-quota recovery for that job
```

#### UC-MQR-11: An operator's interactive session keeps its degraded primary model

```gherkin
Given the operator's interactive launch uses Claude Fable and that model carries a degraded status
When that launch resolves a Claude slow dispatch
Then the launch still runs on its configured primary, Claude Fable
And no chain fallback warning is emitted
```

#### UC-MQR-12: An operator's scheduled job uses an eligible fallback model

```gherkin
Scenario: Continue with an eligible fallback
  Given an operator configured a scheduled job with a model chain whose primary is degraded
  When the job is dispatched
  Then the job runs on the next eligible model
  And a structured warning names the skipped and selected models
  And the agent remains eligible for selection

Scenario: Fail when every model is unavailable
  Given every model in the job's chain is unavailable
  When the job is dispatched
  Then dispatch fails before session creation
  And the agent-wide operator status remains unchanged
```

#### UC-MQR-13: Launch ownership survives restart and revival

#### UC-MQR-14: A job-role launch whose chain holds no eligible model fails typed

#### UC-MQR-15: An operator can inspect and clear model-specific availability

```gherkin
Given an operator sets a model-specific status for an agent
When they inspect or clear that model's status
Then they see the model-level status using the agent-wide status vocabulary
And the agent-wide status remains unchanged
```

## Known caveats

- Silence is not quota evidence.
- Agents with single-entry chains have no fallback: once their model carries a status
  that the launch's ownership excludes, dispatch for that mode fails fast until the
  status expires.
- The chain does not provide cross-agent or cross-harness continuation.
- Model records are written by parent intelligence; no code path classifies
  provider prose.

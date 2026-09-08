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

## Canonical fields

### Model-scoped availability

<!-- planned-change:scoped-agent-model-availability -->
The availability record carries an optional model identifier. A record without a
model is the agent-wide operator status; dispatch eligibility consumes only those
records, unchanged. A record with a model is consumed only by mode-to-model
resolution. Model records support `unavailable` with an explicit until instant taken
from the provider's stated recovery window, and an expired record normalizes back to
available under the existing availability contract. Intelligence, never keyword
matching, decides when a model record is written.
<!-- change:scoped-agent-model-availability -->
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
<!-- /planned-change:scoped-agent-model-availability -->

### Ordered model chains

<!-- planned-change:scoped-agent-model-availability -->
Each agent's thinking-mode mapping is an ordered chain of entries. Every entry
carries its model identifier as data alongside its launch flags. Resolution selects
the first entry whose model has no active model-scoped unavailability record; later
entries are fallbacks for the same declared intent. A single-entry chain is the
default and behaves exactly like today's one mapping.

Claude's `slow` chain is Claude Fable then Claude Opus, both at high effort. Codex
and Gemini currently declare single-entry chains, so no fallback exists for them.
Chain contents are declared per-agent policy: the platform ships defaults, and the
operator configuration may override them per agent and mode. The declaration
surface, its schema, and startup validation are owned by the configuration
contract (`project/spec/teleclaude-config`); chain resolution consumes the
validated policy and never invents a model or substitutes another agent.

Chain resolution applies at every computed launch of an agent process — fresh
dispatch, restart, and revival alike. A session record pins the agent, the native
transcript, and the thinking mode, never a model: launch commands are always
computed from the current mapping, so continuation on a fallback model is the
same computation the platform has always performed when mappings change. No
per-session launch state is recorded anywhere; when a model's unavailability
record expires, the next computed launch returns to the primary automatically.

When resolution selects a non-first entry, it emits one structured warning naming
the agent, mode, skipped model, selected model, and reason. When every entry in the
chain is unavailable, dispatch fails with a typed error before session creation and
the agent-wide status stays untouched.
<!-- change:scoped-agent-model-availability -->
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
contract (`project/spec/teleclaude-config`); chain resolution consumes the
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
<!-- /planned-change:scoped-agent-model-availability -->

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

```gherkin
Given an orchestrated worker fails during startup before producing a transcript
When the parent investigates the failed runtime
Then it reads the supervised terminal before ending the stale session
And it does not infer a cause from silence alone
```

#### UC-MQR-2: Model-specific exhaustion is recorded and retried through the chain

```gherkin
Given terminal evidence establishes that Claude Fable exhausted its own quota
When the parent recovers the job
Then it records Claude Fable unavailable until the provider's stated recovery window
And it ends the stale session
And it retries the identical dispatch once, which resolution launches on Claude Opus
And it does not change the agent-wide operator status
```

#### UC-MQR-3: Recovery preserves the original dispatch

```gherkin
Given a model-specific quota recovery is eligible
When the parent retries the job
Then the job, project, arguments, context, selected agent, and mode are unchanged
And only chain resolution determines the launched model
```

#### UC-MQR-4: Recovery never loops

```gherkin
Given the single recovery retry also fails
When the parent handles that outcome
Then it performs no further model-quota retry
And the job remains an unsuccessful outcome for normal orchestration handling
```

#### UC-MQR-5: Provider-wide failure keeps provider availability semantics

```gherkin
Given direct provider evidence establishes provider-wide quota or instability
When the parent classifies the failure
Then it uses the provider availability recovery contract
And it does not use a model-scoped record as a substitute
```

#### UC-MQR-6: An active model record steers every subsequent dispatch

```gherkin
Given Claude Fable has an active model-scoped unavailability record
When any session resolves a Claude slow dispatch
Then the session launches on Claude Opus without a failed startup
And one structured warning names the skipped and selected models
And Claude remains eligible for dispatch selection
```

#### UC-MQR-7: Expiry restores the primary mapping

```gherkin
Given a model-scoped unavailability record has passed its until instant
When a session resolves a dispatch whose chain lists that model first
Then the session launches on that primary model
And no residual fallback behavior remains
```

#### UC-MQR-8: An exhausted chain fails dispatch without touching agent availability

<!-- planned-change:scoped-agent-model-availability -->
```gherkin
Given every model in an agent's chain for the requested mode has an active record
When a session attempts that dispatch
Then the dispatch fails with a typed error before session creation
And the agent-wide operator status is unchanged
```
<!-- change:scoped-agent-model-availability -->
```gherkin
Given every model in an agent's chain for the requested mode has an active unavailable status
When a session attempts that dispatch
Then the dispatch fails with a typed error before session creation
And the agent-wide operator status is unchanged
```
<!-- /planned-change:scoped-agent-model-availability -->

#### UC-MQR-9: Operator configuration overrides a declared chain

```gherkin
Given the operator configuration declares a chain for an agent's mode
When a session resolves a dispatch for that agent and mode
Then resolution walks the configured chain instead of the platform default
And an invalid chain declaration is rejected at configuration validation, not at dispatch
```

#### UC-MQR-10: A stalled worker recovers mid-session with its transcript intact

```gherkin
Given a dispatched worker's session derives `stalled` during a turn
And the parent captures the pane and intelligence establishes model-specific exhaustion
When the parent recovers the worker
Then it records the exhausted model unavailable until the provider's stated window
And restarts the same session once, whose computed launch resolves the next available chain model
And the session's transcript and job context are preserved
And a failed restart triggers no further model-quota recovery for that job
```

<!-- planned:scoped-agent-model-availability -->
#### UC-MQR-11: A human-owned launch keeps its degraded primary model

```gherkin
Given Claude Fable carries an active degraded status
And a fresh session launch carries no job role
When that launch resolves a Claude slow dispatch
Then the launch runs on Claude Fable
And no chain fallback warning is emitted
```

#### UC-MQR-12: A job-role launch skips a degraded model

```gherkin
Given Claude Fable carries an active degraded status
And a fresh session launch carries a job role
When that launch resolves a Claude slow dispatch
Then the launch runs on Claude Opus
And one structured warning names the skipped model, the selected model, and the launch ownership
And Claude remains eligible for agent selection
```

#### UC-MQR-13: Launch ownership survives restart and revival

```gherkin
Given a session was launched carrying a job role
And a model earlier in its chain carries an active degraded status
When that session is restarted or revived
Then its computed launch skips the degraded model exactly as its original launch did
And a session launched with no job role keeps its degraded primary across the same operations
```

#### UC-MQR-14: A job-role launch whose chain holds no eligible model fails typed

```gherkin
Given every model in an agent's chain for the requested mode is degraded
And a launch carrying a job role attempts that dispatch
Then the dispatch fails with a typed error before session creation
And the agent-wide operator status is unchanged
And a launch carrying no job role runs on the first entry in that same chain
```

#### UC-MQR-15: Model status reaches operator surfaces in the agent-wide vocabulary

```gherkin
Given an operator sets a declared model of an agent to degraded with a reason
When the operator reads agent availability, or a live availability event reaches a client
Then that model appears with the same status vocabulary the agent-wide record uses
And the agent-wide status is unchanged
And clearing the model returns it to available and removes it from the reported records
```

<!-- /planned:scoped-agent-model-availability -->
## Known caveats

- Silence is not quota evidence.
<!-- planned-change:scoped-agent-model-availability -->
- Agents with single-entry chains have no fallback: after their model is recorded
  unavailable, dispatch for that mode fails fast until the record expires.
<!-- change:scoped-agent-model-availability -->
- Agents with single-entry chains have no fallback: once their model carries a status
  that the launch's ownership excludes, dispatch for that mode fails fast until the
  status expires.
<!-- /planned-change:scoped-agent-model-availability -->
- The chain does not provide cross-agent or cross-harness continuation.
- Model records are written by parent intelligence; no code path classifies
  provider prose.

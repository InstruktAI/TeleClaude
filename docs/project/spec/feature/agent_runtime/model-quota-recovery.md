---
description: Bounded recovery when a selected model exhausts its own quota before a worker transcript exists.
delivered_by:
  - model-quota-slow-fallback
---

# Model Quota Recovery — Spec

## What it is

Model-quota recovery preserves an orchestrated job when the selected model exhausts
its own allowance during startup while the provider and harness may still be usable.
The parent reads the failed runtime terminal, classifies the provider prose, removes
the stale session, and retries the same job once through an internal fallback mode.

This recovery is distinct from provider availability. Exhaustion scoped to one model
does not make every model behind the provider unavailable and does not change the
provider-wide operator status.

## Canonical fields

### Internal fallback mode

`slow-fallback` is an internal Claude-only recovery mode. Claude keeps
`--model 'claude-fable-5[1m]' --effort high` as its normal `slow` mapping and uses
`--model 'claude-opus-5[1m]' --effort high` for `slow-fallback`. Codex and Gemini
define no fallback mapping, so the mode cannot be used for them.

The mode is absent from ordinary human choice and is used only after intelligence
establishes model-specific quota exhaustion. A missing mapping makes recovery
unavailable; it never invents a model or silently changes provider.

### Evidence and retry boundary

Startup evidence comes from the supervised terminal when no native transcript exists.
The terminal is captured before the stale session is ended. Intelligence, not keyword
matching, decides whether the provider prose establishes model-specific exhaustion.

The retry preserves the original job, project, arguments, context, and selected agent;
only the thinking mode changes to `slow-fallback`. Recovery ends after one retry.

### Use cases

#### UC-MQR-1: Terminal evidence supports transcriptless startup failure

```gherkin
Given an orchestrated worker fails during startup before producing a transcript
When the parent investigates the failed runtime
Then it reads the supervised terminal before ending the stale session
And it does not infer a cause from silence alone
```

#### UC-MQR-2: Model-specific exhaustion retries through the configured fallback

```gherkin
Given terminal evidence establishes that Claude Fable exhausted its own quota
When the parent recovers the job
Then it ends the stale session
And retries the same job once with Claude Opus through the internal slow fallback
And it does not mark the provider degraded or unavailable
```

#### UC-MQR-3: Recovery preserves the original dispatch

```gherkin
Given a model-specific quota recovery is eligible
When the parent retries the job
Then the job, project, arguments, context, and selected agent are unchanged
And only the thinking mode changes to the internal fallback
```

#### UC-MQR-4: Recovery never loops

```gherkin
Given the single slow-fallback retry also fails
When the parent handles that outcome
Then it performs no further model-quota retry
And the job remains an unsuccessful outcome for normal orchestration handling
```

#### UC-MQR-5: Provider-wide failure keeps provider availability semantics

```gherkin
Given direct provider evidence establishes provider-wide quota or instability
When the parent classifies the failure
Then it uses the provider availability recovery contract
And it does not use model-specific fallback as a substitute
```

## Known caveats

- Silence is not quota evidence.
- Recovery is unavailable for Codex and Gemini because they have no slow-fallback mapping.
- The internal fallback does not provide cross-agent or cross-harness continuation.

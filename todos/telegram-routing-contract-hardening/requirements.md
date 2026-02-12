# Requirements: telegram-routing-contract-hardening

## Goal

Ensure Telegram-bound UI delivery is routed through one deterministic lane and uses explicit success/failure contracts.

## In Scope

1. Remove/close Telegram UI send bypass paths around lane routing.
2. Normalize message/file delivery outcomes to explicit contract semantics.
3. Propagate missing/invalid routing metadata as explicit failure.
4. Add route/recovery/final-outcome observability for this path.

## Out of Scope

1. Invalid-topic suppression/backoff behavior.
2. Ownership/delete-authority hardening.
3. Non-Telegram adapter redesign.

## Success Criteria

- [ ] Telegram UI delivery no longer bypasses lane routing.
- [ ] Message/file send paths do not use empty-string sentinel as success-like outcome.
- [ ] Callers can distinguish delivery success from delivery failure without truthy/falsy ambiguity.
- [ ] Missing topic/channel metadata surfaces as explicit failure.
- [ ] Logs clearly show routing decision, recovery decision, and final delivery result.

## Constraints

1. Keep observer fanout behavior functionally unchanged.
2. Keep changes incremental and compatibility-aware for existing callers.
3. Do not add new hidden fail-open fallbacks.

## Risks

1. Existing callers may rely on previous sentinel/truthy behavior.
2. Contract tightening may expose latent bugs in downstream handling.
3. Route unification may alter edge-case ordering in fanout execution.

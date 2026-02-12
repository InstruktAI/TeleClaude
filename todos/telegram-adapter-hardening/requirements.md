# Requirements: telegram-adapter-hardening

## Goal

Make Telegram message routing and cleanup deterministic, observable, and safe by removing ambiguous fallback behavior and enforcing one delivery path.

## In Scope

1. Route Telegram-bound UI sends through a single lane/funnel.
2. Normalize delivery result contracts for message/file paths.
3. Add bounded suppression/backoff for repeated invalid-topic delete attempts.
4. Centralize orphan-topic delete entrypoint semantics.
5. Harden ownership checks for destructive topic cleanup.
6. Reduce cross-layer coupling between `AdapterClient` and Telegram internals where fallback policy is duplicated.

## Out of Scope

1. Broad redesign of unrelated adapters.
2. UX/visual behavior changes in TUI.
3. Non-Telegram routing behavior except where shared delivery contracts require alignment.

## Success Criteria

- [ ] Telegram UI delivery uses one lane path consistently.
- [ ] Missing/invalid routing does not return success-like sentinel values.
- [ ] Repeated `Topic_id_invalid` attempts are suppressed within a cooldown window.
- [ ] Topic deletion is not executed on weak ownership heuristics alone.
- [ ] Logs/events clearly distinguish route, recovery, and final delivery outcomes.

## Constraints

1. Preserve existing user-facing functional behavior where safe.
2. Keep changes incremental and merge-safe.
3. Avoid introducing new fallback paths that hide delivery failures.

## Risks

1. Tightening contracts may surface latent caller assumptions.
2. Suppression logic may hide legitimate one-off recovery if tuned incorrectly.
3. Refactoring cross-layer responsibilities can introduce regressions without careful sequencing.

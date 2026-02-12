# Breakdown: telegram-adapter-hardening

## Decision

Split required. The parent scope spans multiple subsystems and cannot be completed safely in one atomic implementation session.

## Split Todos

1. `telegram-routing-contract-hardening`
2. `telegram-topic-cleanup-guards`
3. `telegram-ownership-layering-cleanup`

## Rationale

1. Routing/contract normalization is prerequisite behavior for cleanup and ownership hardening.
2. Invalid-topic storm suppression has operational urgency and can be isolated.
3. Ownership + layering cleanup is architectural and should not block urgent behavior fixes.

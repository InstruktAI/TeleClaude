# Input

Current Telegram adapter delivery and cleanup logic has routing/fallback behavior that hides failures and causes repeated invalid-topic cleanup storms.

Observed symptoms:

1. Repeated `Topic_id_invalid` logs from orphan-topic delete paths.
2. Multiple fallback behaviors with weak/ambiguous success contracts.
3. AdapterClient and Telegram adapter contain overlapping routing/recovery responsibilities.
4. Delivery can bypass the single routing funnel in some paths.

Requested outcome:

1. One deterministic delivery funnel for Telegram-bound UI messages.
2. Explicit success/failure contracts (no sentinel empty-string or ambiguous truthy/falsy semantics).
3. Bounded invalid-topic handling (suppression/backoff) instead of repeated storms.
4. Strong ownership checks before destructive cleanup.
5. Cleaner layering between AdapterClient orchestration and Telegram adapter internals.

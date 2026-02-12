# Input

Stop repeated invalid-topic cleanup storms.

Scope:

1. Add suppression/backoff/cooldown for repeated `Topic_id_invalid` delete attempts.
2. Centralize orphan-topic delete entry semantics across callers.
3. Keep cleanup non-destructive when confidence is low.

# Input

Harden Telegram delivery routing contracts.

Scope:

1. Remove/close any Telegram UI send bypasses around the lane funnel.
2. Normalize delivery result contract for message/file paths.
3. Ensure missing/invalid routing metadata surfaces as explicit failure, not sentinel success.

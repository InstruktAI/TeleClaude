# Input

Harden delete ownership checks and reduce adapter-layer coupling.

Scope:

1. Replace weak title-only ownership checks for destructive deletes.
2. Clarify boundaries between AdapterClient orchestration and Telegram fallback policy.
3. Remove duplicated fallback-policy decisions across layers.

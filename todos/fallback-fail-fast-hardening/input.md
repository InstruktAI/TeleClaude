# Input: fallback-fail-fast-hardening

## Context

We have accumulated fallback behavior that violates fail-fast contract discipline:

1. Ingress layers coerce missing required values (for example `project_path`) instead of failing at the boundary.
2. Core handlers introduce broad fallback behavior that hides contract violations (for example defaulting to `help-desk` for missing `project_path` even without explicit restrictive role).
3. Session data retrieval can return ambiguous success-like payloads where state is actually "pending/not available".
4. Telegram fallback paths still create uncertainty around parse-entities failures and footer consistency.
5. Invalid-topic cleanup retries can repeatedly execute with low signal and no suppression memory.

## Why This Todo Exists

The current behavior increases silent failure risk, makes regressions harder to detect, and creates inconsistent operator expectations. We need explicit contracts and explicit errors, not sentinel or implicit fallback behavior.

## Objective

Build a one-by-one hardening pass that removes hidden fail-open behavior and enforces boundary contracts across session creation, session data retrieval, and Telegram delivery/cleanup paths, while preserving the existing explicit non-admin jailing rule.

## Source Material

1. `todos/telegram-fallback-audit-2026-02-12.md`
2. Active findings in `teleclaude/core/command_handlers.py` and mapper ingress paths

# Daemon Crash Recovery and State Recovery — Idea

**Date:** 2026-02-20
**Source:** Recent memory (2025-10-30)
**Priority:** High (recurring reliability issue)

## Summary

Observed multiple instances where daemon enters unrecoverable state after crash. Manual restart required. Message buffering improvements were made but may not address root cause.

## Pattern

1. Daemon crashes during sustained operation
2. Enters unrecoverable state (unclear what this means exactly)
3. Requires manual restart
4. Work in progress is lost or inaccessible

## Symptoms

- Transcription stops working unexpectedly
- Resume/cancel commands fail
- No automatic recovery

## Why This Matters

Reliability is critical for long-running agent work. Crashes without graceful recovery interrupt autonomous execution and force manual intervention.

## Questions to Investigate

- What specific conditions trigger unrecoverable state?
- Can we detect and auto-restart?
- Are there checkpoints/journals for work recovery?
- Message buffering improvements — were they deployed?

## Related

- Daemon availability policy (existing)
- Single database access patterns (existing)
- Session state management

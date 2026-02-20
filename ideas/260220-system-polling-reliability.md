# System Polling Reliability and Continuity — Idea

**Date:** 2026-02-20
**Source:** Recent memory (2025-10-30)
**Priority:** High (reliability concern)

## Summary

User observed system polling stopping unexpectedly. User note: "Why does polling stop? It must always be polling." Suggests polling is a critical background function that occasionally fails.

## Symptom

Polling stops without explicit shutdown or user action. No clear trigger identified.

## Why This Matters

Polling likely monitors session health, daemon status, or event notifications. Loss of polling means loss of visibility into system state, broken heartbeat for long-running work.

## Questions

- What is the polling target? (Daemon health? Events? Sessions?)
- Why does it stop?
- Is there a restart mechanism?
- What's the impact of polling loss?
- Is there a watchdog for the poller itself?

## Related

- Heartbeat/monitoring patterns
- Daemon reliability (see: daemon-crash-recovery idea)
- Session lifecycle management
- System observability

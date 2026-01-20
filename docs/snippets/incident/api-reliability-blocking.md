---
id: incident/api-reliability-blocking
type: incident
scope: global
description: Analysis of how third-party API rate limits can block the daemon.
---

# Incident Analysis: API Blocking

## Symptom
The TeleClaude daemon becomes unresponsive or slow when many AI sessions are running.

## Root Cause
Synchronous calls to third-party APIs (Telegram, OpenAI) in the main event loop or command handlers.

## Mitigation
1. **Async Everywhere**: All I/O must use `aiohttp`, `httpx`, or `aiosqlite`.
2. **Timeouts**: Every external call must have a strict timeout.
3. **Out-of-Process**: Heavy tasks (like voice transcription) should be offloaded or handled with careful concurrency limits.
4. **Availability Marking**: Use `teleclaude__mark_agent_unavailable` to proactively skip rate-limited agents.
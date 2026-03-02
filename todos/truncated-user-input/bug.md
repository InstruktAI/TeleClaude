# Bug: User transcribed input is truncated before delivery to agent sessions. Suspect multiple curl/send paths bypassing the unified message route — violates DRY and adapter boundary policy. Must investigate all code paths that send messages to sessions (telec sessions send, direct API calls, notification delivery, any raw curl to the daemon socket) and consolidate to a single canonical route. Truncation must be handled gracefully — if a message exceeds limits, it should be chunked or the limit raised, never silently cut.

## Symptom

User transcribed input is truncated before delivery to agent sessions. Suspect multiple curl/send paths bypassing the unified message route — violates DRY and adapter boundary policy. Must investigate all code paths that send messages to sessions (telec sessions send, direct API calls, notification delivery, any raw curl to the daemon socket) and consolidate to a single canonical route. Truncation must be handled gracefully — if a message exceeds limits, it should be chunked or the limit raised, never silently cut.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-02

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

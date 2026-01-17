# Async Improvements - Requirements

## Problem Statement

The REST server experiences intermittent unavailability due to blocking operations in async code paths. The event loop is being blocked by synchronous operations, causing the entire server to become unresponsive.

## Goals

1. Eliminate all blocking operations from async code paths
2. Improve database connection resilience
3. Ensure REST API remains responsive under load

## Scope

### In Scope

1. Wrap blocking subprocess calls in `asyncio.to_thread()`
2. Fix blocking psutil calls
3. Add database busy timeout
4. Convert critical file I/O to async with aiofiles

### Out of Scope

- Major architectural changes
- Database migration to different engine
- Full aiofiles conversion (only hot paths)

## Success Criteria

1. No blocking calls in async functions (verified by code review)
2. REST API responds within 100ms under normal load
3. Database operations don't fail due to lock contention

## Reference

See `docs/rest-reliability-analysis.md` for detailed findings.

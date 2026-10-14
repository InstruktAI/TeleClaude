---
description: HTTPX timeout semantics — connect, read, write and pool timeouts each bound one operation; the read timeout bounds the wait for each received chunk, not a response's total duration.
---

# HTTPX Timeouts — Third-Party

## What it is

HTTPX applies timeouts to individual network operations. None of its timeout
types caps the total duration of a request or of a streamed response body.

## Timeout types

- **Connect** — the maximum time to wait until a socket connection to the
  requested host is established; exceeding it raises `ConnectTimeout`.
- **Read** — the maximum duration to wait for a chunk of data to be received;
  exceeding it raises `ReadTimeout`. A response whose chunks keep arriving
  within this bound is not stopped by it, however long the whole body takes.
- **Write** — the maximum duration to wait for a chunk of data to be sent;
  exceeding it raises `WriteTimeout`.
- **Pool** — the maximum duration to wait for a connection from the connection
  pool; exceeding it raises `PoolTimeout`.

All four are subclasses of `httpx.TimeoutException`.

## Configuration

- Default: a `TimeoutException` after 5 seconds of network inactivity.
- A single value (`timeout=10.0`) on a request or a client sets all four.
- `httpx.Timeout(10.0, connect=60.0)` sets one default with per-type overrides.
- `timeout=None` disables timeouts.

## Operational notes

- A bound on the total time to fetch a body is not available from HTTPX
  timeouts; it is applied around the whole operation by the caller (for
  example `asyncio.wait_for` around the streamed download).

## Sources

- https://www.python-httpx.org/advanced/timeouts/

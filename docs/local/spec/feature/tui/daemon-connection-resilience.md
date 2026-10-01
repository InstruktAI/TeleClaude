---
description: "Daemon-connection resilience contract for the running TUI: a daemon
  connection dropped while a TUI request is in flight surfaces as the client's
  handled API failure and the TUI keeps running, retrying its refresh instead of
  crashing."
---

# Daemon Connection Resilience — Spec

## What it is

The TUI talks to the daemon over its local API socket continuously — bootstrap
refreshes, periodic reconciliation, user-triggered actions. The daemon restarts
independently of the TUI, so any of those requests can be cut mid-flight when
the daemon closes the socket before responding.

The resilience contract is a single invariant: every daemon-request failure —
connection refused, timeout, error status, or a connection dropped mid-request
— surfaces to the TUI as the client's handled API failure, never as a raw
transport exception. The TUI stays alive across daemon restarts, logs the
failed refresh, and retries until the daemon is reachable again.

## Canonical fields

### Use cases

#### UC-TDR1: A daemon connection dropped mid-request surfaces as a handled API failure

```
Given the TUI has a request to the daemon in flight
When the daemon closes the connection before sending a response
Then the request failure surfaces as the client's documented API error
And the TUI keeps running and retries the refresh
```

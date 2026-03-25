# Requirements: Output Delivery Redesign

## R1: Adapter-owned output delivery

Adapters pull output on their own cadence. Core signals activity via `last_activity_at`. No output data flows from core to adapters.

## R2: Staleness fix

`_has_active_output_message` must fetch fresh session from DB to prevent stale in-memory origin_metadata.

## R3: Remove user input broadcast

Core does not broadcast user input to adapters. Adapters read from transcripts.

## R4: Unified threaded output

All adapters use threaded output unconditionally. Edit-in-place and THREADED_OUTPUT flag removed.

## R5: Cadence loop infrastructure

Each adapter configures its own output cadence interval. Discord: 1s. Base class provides `OutputCadenceLoop` with transcript pull, render, dedup, and send.

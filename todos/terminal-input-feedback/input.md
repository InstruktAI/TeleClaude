# Input: terminal-input-feedback

## Problem

Terminal users do not see a confirmation indicator when their input is enqueued. After the core inbound queue is implemented, terminal input routes through the enqueue boundary (formerly `process_message`), but there's no visual signal to confirm receipt. Users should know their input was received.

This is a deferred enhancement from the guaranteed-inbound-delivery build phase.

## Scope

Implement a TUI status indicator showing "message received" when terminal input is enqueued:

1. Identify the TUI event bus or notification mechanism used by the terminal interface.
2. Fire a "message enqueued" event after `process_message` returns from the terminal path.
3. Render status indicator in the TUI (e.g., "✓ Message queued" or equivalent visual cue).
4. Clear indicator after a brief timeout (1-2 seconds) or when agent starts responding.

## Deliverables

1. Audit the TUI rendering layer to understand event bus / notification pattern.
2. Add "message_enqueued" event dispatch after successful terminal `process_message` call.
3. Implement TUI status indicator with brief display timeout.
4. Tests: verify indicator appears on enqueue; verify it disappears after timeout.

## Definition of Done

- Terminal users see a visual confirmation indicator within 100ms of pressing Enter.
- Indicator persists for ~1 second or clears when agent output appears.
- Indicator does not interfere with subsequent input or agent output rendering.
- Tests pass; TUI tested in isolation.

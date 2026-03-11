# Bug: EventProducer.emit() silently fails to write domain events to Redis stream. Stream has 0 consumer groups and only 7 old content.dumped entries (direct xadd). Zero deployment.started, branch.pushed, or review.approved events ever landed despite emit calls succeeding without exceptions. IntegrationTriggerCartridge never fires. Root cause: likely broken Redis client reference in EventProducer, or xadd returning success without writing. Immediate fix: add logging to EventProducer.emit (event type, entry_id) and to emit_event (before/after). This broke the finalize→integrator spawn chain.

## Symptom

EventProducer.emit() silently fails to write domain events to Redis stream. Stream has 0 consumer groups and only 7 old content.dumped entries (direct xadd). Zero deployment.started, branch.pushed, or review.approved events ever landed despite emit calls succeeding without exceptions. IntegrationTriggerCartridge never fires. Root cause: likely broken Redis client reference in EventProducer, or xadd returning success without writing. Immediate fix: add logging to EventProducer.emit (event type, entry_id) and to emit_event (before/after). This broke the finalize→integrator spawn chain.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-11

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

# Bug: asyncio task accumulation: Pipeline.execute() has no backpressure on domain_pipeline_fanout tasks, causing unbounded growth (observed 6790 tasks vs 500 threshold). Secondary: tmux_io.py untracked fire-and-forget DB update task; monitoring_service._check_pressure does not log task name breakdown.

## Symptom

asyncio task accumulation: Pipeline.execute() has no backpressure on domain_pipeline_fanout tasks, causing unbounded growth (observed 6790 tasks vs 500 threshold). Secondary: tmux_io.py untracked fire-and-forget DB update task; monitoring_service._check_pressure does not log task name breakdown.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-19

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

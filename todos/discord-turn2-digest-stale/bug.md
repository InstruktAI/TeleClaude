# Bug: Discord threaded output fails on turn 2+ — incremental render digest falsely matches previous turn, suppressing delivery

## Symptom

Discord threaded output fails on turn 2+ — incremental render digest falsely matches previous turn, suppressing delivery

## Detail

After turn 1 delivers successfully to Discord, turn 2 agent response is suppressed by unchanged_render_digest in _incremental.py. The agent_stop event fires, incremental analysis runs, but the digest from turn 1 is still cached and matches (falsely) even though content changed. The New turn detection fires but the digest comparison still blocks. Root cause: the render digest is not properly invalidated on turn break, or the rendered content for both turns hashes identically due to formatting overlap.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-25

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

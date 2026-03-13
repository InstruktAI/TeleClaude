# Bug: Integration state machine infinite loop on already-delivered squash merges. Ancestor check (merge-base --is-ancestor) is SHA-based and always fails for squash merges. Worktree reset on re-entry discards conflict resolutions. Affected: teleclaude/core/integration/state_machine.py (ancestor check ~L813, worktree reset ~L431, empty squash guard ~L834).

## Symptom

Integration state machine infinite loop on already-delivered squash merges. Ancestor check (merge-base --is-ancestor) is SHA-based and always fails for squash merges. Worktree reset on re-entry discards conflict resolutions. Affected: teleclaude/core/integration/state_machine.py (ancestor check ~L813, worktree reset ~L431, empty squash guard ~L834).

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-13

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

# Bug: telec bugs report bypasses event system with direct session spawn

## Symptom

telec bugs report bypasses event system with direct session spawn

## Detail

_handle_bugs_report directly calls api.create_session() instead of emitting an event. Should emit domain.software-development.planning.bug_reported and let a cartridge spawn the work orchestrator, matching the pattern of todo dump and content dump. Additionally: --description flag was never implemented, <description> is still positional against CLI no-positionals policy.

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

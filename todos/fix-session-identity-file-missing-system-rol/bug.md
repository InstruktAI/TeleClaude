# Bug: Session identity file missing system_role and human_role after daemon restart — git wrapper rejects all commands

## Symptom

Session identity file missing system_role and human_role after daemon restart — git wrapper rejects all commands

## Detail

Identity file at ~/.teleclaude/tmp/sessions/{session_id}/teleclaude_identity.json contains only {"session_id": "..."} after daemon restart. Missing system_role and human_role fields. The git wrapper requires these to determine permissions, so ALL git commands fail for the session. The identity file write is not atomic — either the daemon writes fields incrementally (race condition) or the restart path doesn't re-bootstrap existing sessions. Observed in session 2ecf8c0d-9a22-4e0f-b609-1a9f13eb4930 after make restart.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-24

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

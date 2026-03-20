# Bug: Integration handoff chain breaks silently — readiness projection loses state on daemon restart, no observability at any step. The entire chain from mark-finalize-ready through event emission, pipeline processing, readiness projection, to integrator notification has zero warning-level logging when events are ingested but no READY candidate is produced. Need warning logs at every step: (1) _ingest_callback when projection returns empty, (2) spawn_integrator_session when called vs skipped, (3) readiness projection when it receives events for unknown candidates.

## Symptom

Integration handoff chain breaks silently — readiness projection loses state on daemon restart, no observability at any step. The entire chain from mark-finalize-ready through event emission, pipeline processing, readiness projection, to integrator notification has zero warning-level logging when events are ingested but no READY candidate is produced. Need warning logs at every step: (1) _ingest_callback when projection returns empty, (2) spawn_integrator_session when called vs skipped, (3) readiness projection when it receives events for unknown candidates.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-20

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

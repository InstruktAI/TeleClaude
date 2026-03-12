# Bug: daemon Python code calls telec CLI via subprocess instead of service layer

## Symptom

daemon Python code calls telec CLI via subprocess instead of service layer

## Detail

teleclaude/core/next_machine/core.py:529 calls telec todo demo validate and teleclaude/core/integration/state_machine.py:942 calls telec todo demo create via subprocess from within the daemon process. CLI is a one-way adapter over the service layer. These operations need to be lifted into a service layer function so the daemon can call them directly. Distinct from fix-integrator-spawn-broken-integration-brid which covers integration_bridge.py.

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

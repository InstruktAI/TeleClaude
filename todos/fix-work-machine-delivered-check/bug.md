# Bug: telec todo work returns ITEM_NOT_READY for delivered slugs when state.yaml is missing — get_item_phase defaults to pending instead of checking delivered.yaml first

## Symptom

telec todo work returns ITEM_NOT_READY for delivered slugs when state.yaml is missing — get_item_phase defaults to pending instead of checking delivered.yaml first

## Detail

When the integrator delivers a slug and cleans up the todo folder (deleting state.yaml), get_item_phase in slug_resolution.py falls through to ItemPhase.PENDING because state.get('phase') returns None on missing file. The DONE check at line 297 of work.py never fires because phase is never 'done'. Fix: check delivered.yaml in get_item_phase (or _validate_explicit_slug_readiness) before falling back to pending. If slug is in delivered.yaml, return DONE immediately.

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

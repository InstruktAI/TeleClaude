# Bug: asyncio tasks unnamed: ~30 create_task calls lack name= parameter, making task leak diagnosis impossible. Pressure logs show all 1100+ leaking tasks as generic Task-N. Need to add descriptive names to every call site.

## Symptom

asyncio tasks unnamed: ~30 create_task calls lack name= parameter, making task leak diagnosis impossible. Pressure logs show all 1100+ leaking tasks as generic Task-N. Need to add descriptive names to every call site.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-21

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

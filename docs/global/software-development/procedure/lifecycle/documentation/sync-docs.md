---
description: Sync docs and indexes after documentation changes.
id: software-development/procedure/lifecycle/documentation/sync-docs
scope: domain
type: procedure
---

# Sync Docs — Procedure

## Goal

After any documentation change, run `telec sync`.

## Preconditions

- `telec` is available.

## Steps

1. Run `telec sync`.

## Outputs

- Updated `docs/` and regenerated `docs/index.yaml`.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.
